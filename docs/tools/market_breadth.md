# `quantagent/tools/market_breadth.py`

Market breadth, market-timing, and regime-detection tools. The module is split
into two tiers:

- **Fast path** (index/ETF data only) — `count_distribution_days`,
  `detect_follow_through_day`, `compute_market_sentiment`, and the sector-ETF
  proxy branch of `compute_percent_above_ma` / `detect_market_regime`. These
  hit only a handful of tickers and always finish in seconds.
- **Deep path** (universe-level, backed by `BreadthStore`) — the true
  advance/decline line, new highs/lows, percent-above-MA, and breadth thrust
  for hundreds of symbols (e.g. the S&P 500). Slow on the very first call
  (cache warm-up), incremental and fast after that. See
  `docs/tools/breadth_store.md` for the caching layer these rely on.

The methodology throughout is classic O'Neil/CANSLIM/IBD-style market timing
(distribution days, Follow-Through Days) plus Zweig-style breadth thrust and a
standard advance/decline line, wrapped in a hand-built composite regime score.

---

## count_distribution_days

**Agent-facing tool name:** `count_distribution_days`

**Purpose:** Counts IBD-style "distribution days" — down days on rising
volume — on an index over a trailing window, as a proxy for institutional
selling pressure.

**Why built this way:** O'Neil's distribution-day count is a single-index,
single-symbol calculation, so it needs no universe cache — it always uses the
fast path (one `get_ohlcv` call, 6 months of history). The 0.2% decline
threshold and 25-session window are the standard IBD definitions: small
enough to catch routine institutional selling, but requiring higher volume
than the prior session so ordinary low-volume drift doesn't count. Five or
more distribution days in a 25-session window is IBD's classic "market under
pressure" trigger; the code also adds a softer "caution" tier at 3+ that IBD
practice treats as an early warning.

**Math:**
- A session is a **distribution day** when both hold:
  - `pct_change(Close) <= -0.002` (close down at least 0.2%)
  - `Volume > Volume.shift(1)` (higher volume than the prior session)
- Counted over the trailing `lookback_days` sessions (default **25**) of a
  6-month history pull.
- Signal thresholds (`_distribution_signal`):
  - `count >= 5` → `"under-pressure"`
  - `count >= 3` → `"caution"`
  - otherwise → `"healthy"`

**Usage:**
- Parameters: `provider` (data provider), `index_symbol` (default `"SPY"`;
  `"QQQ"` also common), `lookback_days` (default `25`).
- Returns: `{index_symbol, lookback_days, count, dates, signal}` where `dates`
  is the ISO list of qualifying session dates.
- Example: `await count_distribution_days(provider, index_symbol="QQQ", lookback_days=25)`
  → `{"index_symbol": "QQQ", "lookback_days": 25, "count": 4, "dates": [...], "signal": "caution"}`

---

## detect_follow_through_day

**Agent-facing tool name:** `detect_follow_through_day`

**Purpose:** Detects an O'Neil Follow-Through Day (FTD) — the classic
confirmation that a new market uptrend has begun after a correction.

**Why built this way:** Like distribution days, this is single-index and
needs only 6 months of daily bars, so it's fast-path only. The algorithm
follows O'Neil's method exactly: find the correction low, then scan forward
day-by-day for the first qualifying rally session. Rally day 4+ is required
because O'Neil found FTDs on days 1-3 are unreliable (too early, often false
starts); day 4 onward is where the historical hit rate improves. The 1.25%
minimum gain plus higher volume mirrors the distribution-day volume
requirement in reverse — a rally attempt needs a demonstrable increase in
buying demand, not just any up day.

**Math:**
- `window` = trailing `lookback_days` sessions (default **60**) of a 6-month
  pull.
- `correction_low_date` = the date of the lowest `Close` in `window`
  (`argmin`).
- From that low forward (`after`), each session's **rally day** index is its
  position after the low (low itself = rally day 0).
- A **Follow-Through Day** is the first session at **rally day ≥ 4** where
  both hold:
  - `pct_change(Close) >= 0.0125` (gain of at least 1.25%)
  - `Volume > Volume.shift(1)` (higher volume than the prior session)
- Status (`_ftd_status`):
  - FTD found → `"confirmed-uptrend"`
  - no FTD yet, but `rally_day >= 1` and last close > close at the low →
    `"rally-attempt"`
  - otherwise → `"correction"`

**Usage:**
- Parameters: `provider`, `index_symbol` (default `"SPY"`), `lookback_days`
  (default `60`).
- Returns: `{index_symbol, correction_low_date, rally_day, ftd_detected,
  ftd_date, status}`.
- Example: `await detect_follow_through_day(provider, index_symbol="SPY")`
  → `{"index_symbol": "SPY", "correction_low_date": "2025-04-08", "rally_day": 6,
  "ftd_detected": true, "ftd_date": "2025-04-14", "status": "confirmed-uptrend"}`

---

## compute_percent_above_ma

**Agent-facing tool name:** `compute_percent_above_ma`

**Purpose:** Computes the percentage of a universe's members whose latest
close is above each of several moving averages — a classic breadth-of-
participation gauge (are most stocks trending up, or is the index being
carried by a few names?).

**Why built this way:** For `universe="sector_etfs"` there are only 11
tickers, so the function fetches them directly (fast path, 2y of daily bars)
and never touches the cache. For real universes (`sp500`, `nasdaq100`), it
delegates to `BreadthStore` via `_load_universe_closes`: computing "percent
above 200-day MA" across 500 symbols every call would mean re-downloading 500
symbols' history each time, which is why the incremental cache exists. If the
store is cold and `allow_warmup=False` (the default the agent tool uses), the
function degrades gracefully to the sector-ETF proxy rather than blocking or
erroring — the result is flagged `proxy: true` so callers know it's an
approximation. Any exception from the store (e.g. transient I/O) is caught
and logged, falling back the same way rather than propagating.

**Math:**
- Default `ma_periods = [20, 50, 200]` (session counts, i.e. SMA-20/50/200).
- For each period `p` and each symbol's close series with at least `p`
  observations: "above" iff `latest_close > mean(last p closes)` (simple
  moving average, not exponential).
- `pct_above[p] = round(count_above / n_eligible * 100, 2)`; `None` if no
  symbol has enough history for that period.

**Usage:**
- Parameters: `provider`, `universe` (default `"sector_etfs"`; also `"sp500"`,
  `"nasdaq100"`), `ma_periods` (default `[20, 50, 200]`), `allow_warmup`
  (default `True` at the library level; the agent tool pins it to `False` so
  it never blocks on a slow warm-up — see `warm_breadth_cache`).
- Returns: `{universe, proxy, n_symbols, pct_above: {period: pct_or_null}}`.
- Example: `await compute_percent_above_ma(provider, universe="sp500", allow_warmup=False)`
  → `{"universe": "sp500", "proxy": false, "n_symbols": 503,
  "pct_above": {"20": 61.2, "50": 54.8, "200": 68.1}}` (or `proxy: true` with
  the sector-ETF numbers if the sp500 cache is cold).

---

## compute_advance_decline

**Agent-facing tool name:** `compute_advance_decline`

**Purpose:** Computes the classic advance/decline (A/D) line for a universe —
the running total of (advancing symbols − declining symbols) per day, the
oldest and most direct measure of market breadth.

**Why built this way:** This is inherently a deep-path, universe-wide
calculation (every symbol counted every day), so it always warms/loads via
`BreadthStore` (`allow_warmup=True` here — this is the one breadth function
where the library itself will pay the warm-up cost rather than degrading to
a proxy, since there is no sensible ETF proxy for a true breadth line). If the
store can't be loaded, an empty `DataFrame` is returned rather than raising,
so downstream report code can check `.empty` safely.

**Math:**
- `diff = closes.diff()` per symbol (skip the first row, which is `NaN` for
  every symbol).
- `Advancing` = count of symbols with `diff > 0` per day; `Declining` = count
  with `diff < 0`; `Unchanged` = count with `diff == 0`.
- `NetAdvancing = Advancing - Declining`.
- `ADLine = cumsum(NetAdvancing)` — the running A/D line.
- `ADLine_SMA10`, `ADLine_SMA20` — 10- and 20-day simple moving averages of
  the A/D line, for trend confirmation/divergence reading.
- Trimmed to the trailing window implied by `period` via `_HISTORY_DAYS`:
  `1m` → 21, `3m` → 63, `6m` → 126, `1y` → 252 sessions.

**Usage:**
- Parameters: `provider`, `universe` (default `"sp500"`; also `"nasdaq100"`,
  `"sector_etfs"`), `period` (`"1m"|"3m"|"6m"|"1y"`, default `"3m"`).
- Returns: a `DataFrame` indexed by date with columns `Advancing, Declining,
  Unchanged, NetAdvancing, ADLine, ADLine_SMA10, ADLine_SMA20` (empty if the
  universe can't be loaded).
- The agent tool (`compute_advance_decline`) serializes this via
  `_history_payload` to `{latest: {...}, recent: {...last 10 rows...}}`.
- Example: `await compute_advance_decline(provider, universe="sp500", period="3m")`.

---

## compute_new_highs_lows

**Agent-facing tool name:** `compute_new_highs_lows`

**Purpose:** Counts, per day, how many universe members made a new 52-week
high or low — another classic breadth measure, and one of Zweig's key inputs
for spotting broad-based rallies/selloffs versus narrow ones.

**Why built this way:** Requires the full close-price matrix for the
universe over at least a year, so it is deep-path only via `BreadthStore`.
`min_periods=126` on the rolling window means a symbol needs at least ~6
months of history before it's eligible to register a new high/low — this
avoids newly-listed or thinly-backed symbols spuriously registering "new
highs" on day one of their available history.

**Math:**
- `roll_max`/`roll_min` = rolling 252-session max/min of close, with
  `min_periods=126` (so a symbol needs ≥126 sessions before it counts).
- **NewHighs** (per day) = count of symbols where `close >= roll_max` (and
  `roll_max` is defined); **NewLows** = count where `close <= roll_min`.
- `NetNewHighs = NewHighs - NewLows`.
- `HighLowRatio = NewHighs / (NewHighs + NewLows)`, rounded to 4 decimals;
  undefined (`NaN`) on days with zero highs+lows.
- `HL_SMA10` = 10-day SMA of `HighLowRatio`, rounded to 4 decimals.
- Trimmed to the `period` window via the same `_HISTORY_DAYS` map as
  `compute_advance_decline` (1m=21, 3m=63, 6m=126, 1y=252).

**Usage:**
- Parameters: `provider`, `universe` (default `"sp500"`), `period` (default
  `"3m"`).
- Returns: a `DataFrame` indexed by date with columns `NewHighs, NewLows,
  NetNewHighs, HighLowRatio, HL_SMA10` (empty if the universe can't be
  loaded).
- The agent tool serializes via `_history_payload` the same way as
  advance/decline.
- Example: `await compute_new_highs_lows(provider, universe="nasdaq100", period="6m")`.

---

## compute_breadth_thrust

**Agent-facing tool name:** `compute_breadth_thrust`

**Purpose:** Computes a McClellan-style breadth oscillator: the spread
between two EMAs of the ratio-adjusted daily net advances, used to detect
breadth "thrusts" (broad, forceful moves) analogous to Zweig's original
Breadth Thrust indicator.

**Why built this way:** Same rationale as A/D and new highs/lows — needs the
full universe close matrix, so it's deep-path only. The 19/39-day EMA spans
are the standard McClellan Oscillator parameters (McClellan used 19- and
39-day EMAs of daily net advances as an approximation of 10% and 5% trend
smoothing constants); this module reuses that convention rather than
inventing new spans, since it's a well-established and widely recognized
breadth-momentum measure. Scaling the net-advance ratio by 1000 (rather than
using a percentage or raw count) matches the traditional McClellan
presentation so the ±50 thresholds read the same as in classic charting
services.

**Math:**
- `diff = closes.diff()`; `advancing`/`declining` = per-day counts as in the
  A/D calculation.
- `total = advancing + declining`.
- `NetRatio = (advancing - declining) / total * 1000` (NaN/undefined when
  `total == 0`).
- `EMA19 = NetRatio.ewm(span=19).mean()`; `EMA39 = NetRatio.ewm(span=39).mean()`.
- `Oscillator = EMA19 - EMA39` — this is the breadth-thrust value, rounded to
  2 decimals throughout the returned history.
- Signal (`_thrust_signal`) on the latest oscillator value:
  - `> 50` → `"bullish"`
  - `< -50` → `"bearish"`
  - otherwise → `"neutral"`
- History trimmed via `_HISTORY_DAYS[period]` as above.

**Usage:**
- Parameters: `provider`, `universe` (default `"sp500"`), `period` (default
  `"3m"`).
- Returns: `{thrust_value, thrust_signal, history: DataFrame[NetRatio, EMA19,
  EMA39, Oscillator]}`; `thrust_value=None, thrust_signal="unavailable"` and
  an empty history when the universe can't be loaded.
- The agent tool pops `history` out and replaces it with `recent` (last 10
  rows as JSON) before returning.
- Example: `await compute_breadth_thrust(provider, universe="sp500", period="3m")`
  → `{"thrust_value": 62.3, "thrust_signal": "bullish", "history": <DataFrame>}`.

---

## detect_market_regime

**Agent-facing tool name:** `detect_market_regime`
*(Note: the agent-facing wrapper `_detect_market_regime` takes no parameters
of its own — it always calls the library function with its default
`universe="sp500"`; the LLM cannot choose a different universe for this
particular tool.)*

**Purpose:** Produces a single composite 0-100 market-regime score — blending
cross-asset ratios, index trend, volatility, and breadth — mapped to a
regime label (`strong-bull` … `strong-bear`) and a recommended equity
exposure percentage range, intended as top-level "how aggressive should I be
right now" guidance.

**Why built this way:** No single indicator reliably calls a regime, so the
design averages nine independent, economically-motivated signals (each
scored to `[-1, 1]`) rather than relying on one. Cross-asset ratios
(equal-weight vs. cap-weight, small-cap vs. large-cap, cyclicals vs.
defensives, stocks vs. bonds, high-yield vs. investment-grade credit) capture
risk appetite and market internals that a single index price can't; trend and
VIX capture the more traditional technical/volatility view; sector breadth
and participation add a cross-check on how broad-based the move is. Breadth
prefers the deep, universe-warmed score when the cache happens to already be
warm (`_deep_breadth_score`), but **never blocks or triggers a warm-up** to
get it (`allow_warmup=False`) — regime detection is meant to always return
promptly, so it silently falls back to the sector-ETF proxy
(`breadth_source: "sector-etf-proxy"`) when the universe cache is cold.
Missing components (e.g. VIX provider outage) don't break the computation —
they're simply dropped from the weighted average and the weights of the
remaining components are renormalized, and a `confidence` score reports what
fraction of available components agree in direction with the composite.

**Math:**

Component scores (each in `[-1, 1]`, `None` if data unavailable):

| Component | Formula | Notes |
|---|---|---|
| `concentration` | `_ratio_score(RSP/SPY, scale=0.05)` | equal-weight vs cap-weight — breadth/participation proxy |
| `size` | `_ratio_score(IWM/SPY, scale=0.05)` | small-cap vs large-cap — risk appetite |
| `cyclical_defensive` | `_ratio_score(XLY/XLP, scale=0.05)` | cyclicals vs defensives |
| `stock_bond` | `_ratio_score(SPY/TLT, scale=0.10)` | stocks vs long bonds |
| `credit` | `_ratio_score(HYG/LQD, scale=0.03)` | high-yield vs investment-grade credit spread proxy |
| `trend` | `_trend_score(SPY)` | `+0.5` if close > 50-SMA, `+0.5` if close > 200-SMA (else `-0.5` each); range `{-1, 0, 1}` |
| `volatility` | `_vix_score(vix)` | step function on VIX level (below) |
| `breadth` | deep universe score if warm, else sector-ETF `% above 50-SMA` rescaled | `round(pct/50 - 1, 4)` |
| `participation` | % of sector ETFs with positive 1-month return, rescaled | `round(pct_positive*2 - 1, 4)` |

`_ratio_score(num, den, scale)`: computes the 63-session change of
`num.Close / den.Close` (`ratio[-1]/ratio[-64] - 1`), divides by `scale`, and
clips to `[-1, 1]`. `scale` sets how large a 63-day ratio move is needed to
reach a full ±1 (e.g. a 5% move in RSP/SPY over ~1 quarter maxes out
`concentration`; a 10% move is needed to max out `stock_bond`; only 3% for
`credit`, reflecting how much more sensitive credit spreads are).

`_vix_score(vix)` (VIX levels, lower = more bullish):
- `vix < 15` → `1.0`
- `15 ≤ vix < 20` → `0.5`
- `20 ≤ vix < 25` → `0.0`
- `25 ≤ vix < 30` → `-0.5`
- `vix ≥ 30` → `-1.0`
- `vix` unavailable → `0.0`

**Weights** (`_COMPONENT_WEIGHTS`, sum to 1.0):

| Component | Weight |
|---|---|
| concentration | 0.10 |
| size | 0.10 |
| cyclical_defensive | 0.10 |
| stock_bond | 0.10 |
| credit | 0.10 |
| **trend** | **0.20** (double weight — the only component weighted 2x) |
| volatility | 0.10 |
| breadth | 0.10 |
| participation | 0.10 |

`weighted = Σ(weight_i * score_i) / Σ(weight_i)` over available (non-`None`)
components only (renormalized denominator).

`composite = round(50 * (1 + weighted), 2)` — maps `weighted ∈ [-1, 1]` onto
a `[0, 100]` score, 50 being neutral.

**Regime bands** (`_REGIME_BANDS`, first matching threshold from the top
wins — i.e. `composite >= threshold`):

| Score ≥ | Regime | Exposure band (min–max %) | Exposure label |
|---|---|---|---|
| 80 | `strong-bull` | 90–100% | strong |
| 60 | `bull` | 70–90% | healthy |
| 40 | `neutral` | 50–70% | neutral |
| 20 | `bear` | 40–60% | weakening |
| 0 | `strong-bear` | 25–40% | critical |

`exposure_band(score)` is the same mapping exposed as a standalone helper
(returns just the `{min_pct, max_pct, label}` dict for a given 0-100 score),
usable outside the full regime-detection call — e.g. by other tools that
already have a composite score and just need the exposure guidance.

`confidence = round(agreeing / len(available), 4)` where `agreeing` counts
components whose sign matches the sign of `weighted`; defaults to `0.5` when
there's no clear direction (`weighted == 0`) or no data at all.

**Usage:**
- Parameters: `provider`, `universe` (default `"sp500"`; only the underlying
  library function accepts this — the agent tool always uses `"sp500"`).
- Returns: `{regime, score, confidence, recommended_exposure: {min_pct,
  max_pct, label}, components: {cross_asset: {...}, trend_direction,
  volatility_regime, breadth_health, sector_participation, scores,
  breadth_source}, as_of}`.
- Example: `await detect_market_regime(provider, universe="sp500")`
  → `{"regime": "bull", "score": 67.4, "confidence": 0.78,
  "recommended_exposure": {"min_pct": 70, "max_pct": 90, "label": "healthy"},
  "components": {...}, "as_of": "2026-08-15"}`.

---

## compute_market_sentiment

**Agent-facing tool name:** `compute_market_sentiment`

**Purpose:** A fast, "fear & greed"-style composite sentiment score from -100
(extreme fear) to +100 (extreme greed), blending VIX level and term
structure, sector-ETF breadth, and SPY momentum.

**Why built this way:** This is explicitly fast-path only — it never touches
`BreadthStore` (breadth here always comes from `compute_percent_above_ma(...,
universe="sector_etfs")`, 11 tickers) so it always returns quickly regardless
of cache state, useful as a cheap standalone mood check distinct from the
heavier `detect_market_regime`. Put/call ratio is a standard "fear & greed"
input the code deliberately reports as `None` because none of the current
data providers supply it — rather than silently omitting the field, it's kept
in the output schema with a null value so downstream consumers know it's a
recognized-but-unavailable input, not a bug.

**Math:**
- `vix_score = _vix_score(vix) * 100` (reuses the same step function as
  regime detection, scaled to ±100 instead of ±1).
- `vix_term_structure`: `"contango"` if `VIX < VIX3M`, else `"backwardation"`
  (`None` if either is unavailable).
  - `_term_structure_score`: `contango → +25`, `backwardation → -50`
    (asymmetric — backwardation, historically rarer and associated with
    acute stress, is weighted as a stronger negative signal than contango is
    a positive one).
- `breadth = round(pct_above_50sma * 2 - 100, 2)` where `pct_above_50sma`
  comes from the sector-ETF `compute_percent_above_ma` at the 50-day MA
  (rescales 0-100% to -100..+100).
- `momentum` (`_momentum_score`, SPY 1-year history):
  - `ret_1m = close[-1]/close[-22] - 1`, `ret_3m = close[-1]/close[-64] - 1`
  - `raw = (ret_1m / 0.03 + ret_3m / 0.06) / 2` — i.e. a 3% one-month move or
    a 6% three-month move each maxes out its half of the average
  - clipped to `[-1, 1]` then scaled to `[-100, 100]`
- `score = round(mean(available components), 2)` over
  `[vix_score, term_structure_score, breadth, momentum]`, skipping any
  `None`s; `0.0` if none are available.
- Label bands (`_SENTIMENT_LABELS`, first matching threshold wins):
  - `score >= 60` → `"extreme-greed"`
  - `score >= 20` → `"greed"`
  - `score >= -20` → `"neutral"`
  - `score >= -60` → `"fear"`
  - otherwise → `"extreme-fear"`

**Usage:**
- Parameters: `provider` only.
- Returns: `{score, label, components: {put_call_ratio: null, vix_level,
  vix_term_structure, breadth_score, momentum_score}}`.
- Example: `await compute_market_sentiment(provider)`
  → `{"score": 34.2, "label": "greed", "components": {"put_call_ratio": null,
  "vix_level": 14.8, "vix_term_structure": "contango", "breadth_score": 22.0,
  "momentum_score": 41.6}}`.
