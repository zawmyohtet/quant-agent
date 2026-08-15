# Technical Analysis Tools

`quantagent/tools/technical.py` is the price-action toolbox for the agent: it computes standard
indicators on OHLCV data (via the `pandas-ta` DataFrame accessor), detects candlestick patterns
and support/resistance levels with plain vectorized pandas/numpy logic, generates rule-based
trading signals for the backtester, and rolls all of the above up into compact summaries the LLM
can reason over without seeing raw price series. Everything here operates on a standard OHLCV
`pandas.DataFrame` (columns `Open, High, Low, Close, Volume`, `DatetimeIndex`) produced upstream by
`quantagent.tools.market_data.get_ohlcv`.

---

## compute_indicators

**Agent-facing tool name:** `compute_technical_indicators` (wraps `_compute_technical_indicators` in `quantagent/agent/tools_registry.py`, bound via `_bind_provider`)

**Purpose:** Attaches one or more named technical indicators (moving averages, oscillators,
volatility bands, volume/trend measures) as extra columns on an OHLCV DataFrame, so a trader can
ask "what's the RSI-14 and MACD on AAPL right now" and get back the latest computed values.

**Why built this way:** Rather than hand-implementing each indicator, the function registers
`pandas_ta` on import (`import pandas_ta  # noqa: F401`) purely for its side effect of adding a
`.ta` accessor to every DataFrame, then dispatches each requested indicator spec string (e.g.
`"rsi_14"`, `"macd"`) to a small handler that calls the matching `.ta.<indicator>(..., append=True)`
method. This keeps the math itself out of the codebase (delegated to a maintained library) while
giving the agent a simple, LLM-friendly string vocabulary instead of a rigid parameter schema.
Handlers are looked up by string **prefix** in `_INDICATOR_DISPATCH` (checked in insertion order via
`spec.startswith(prefix)`), which lets `sma_20`, `sma_50`, etc. all route through one `_compute_sma`
handler that parses the trailing `_N` as the lookback length. Indicators without a length (`macd`,
`bbands`, `obv`, `stoch`, `vwap`, `supertrend`) are computed with **pandas-ta's own defaults** since
the code never overrides them:
- `macd`: fast=12, slow=26, signal=9 → columns `MACD_12_26_9`, `MACDh_12_26_9`, `MACDs_12_26_9`
- `bbands`: length=5, std=2.0 → columns `BBL_5_2.0_2.0`, `BBM_5_2.0_2.0`, `BBU_5_2.0_2.0`, plus bandwidth/percent columns
- `stoch`: %K length=14, %D=3, smoothing=3
- `supertrend`: ATR length=7, multiplier=3.0
- `vwap`: requires a `DatetimeIndex` (satisfied by `get_ohlcv`'s output)

Each indicator is computed inside its own `try/except` in `_compute_single_indicator`: a failure on
one spec (bad length, unsupported column, etc.) is logged as a warning and skipped rather than
aborting the whole call — so a single typo'd indicator in a multi-indicator request doesn't blow up
the rest of the response. Unknown spec strings that match no prefix are similarly logged and
silently dropped (`_dispatch_indicator`).

**Math:** Delegated to `pandas-ta`; no custom formulas are implemented in this function beyond
string parsing. See individual pandas-ta indicator docs for exact formulas (e.g. RSI here uses
pandas-ta's own `rsi()`, which itself defaults to Wilder/RMA smoothing — see `wilder_rsi` below for
a note on the standalone, faster variant used elsewhere in the codebase).

**Usage:**
- `compute_indicators(df: pd.DataFrame, indicators: list[str]) -> pd.DataFrame`
  - `df`: OHLCV DataFrame.
  - `indicators`: list of spec strings, lower-cased and stripped internally. Supported specs per
    the tool's own docstring: `sma_N`, `ema_N`, `rsi_N`, `macd`, `bbands`, `atr_N`, `adx_N`, `obv`,
    `stoch_k` / `stoch_d` (both trigger the same `stoch()` call), `vwap`, `supertrend`.
  - Returns the original DataFrame with indicator columns appended (input is copied first, not
    mutated).
- Agent tool `compute_technical_indicators(symbol: str, indicators: str)`: fetches 1 year of daily
  OHLCV for `symbol` via `get_ohlcv`, splits the comma-separated `indicators` string, computes them,
  and returns just the latest row (`Close` + the new indicator columns) as JSON — the full history
  isn't sent back to the LLM.
  - Example call: `compute_technical_indicators(symbol="AAPL", indicators="sma_20, rsi_14, macd, bbands")`
- Referenced by the `indicator-playbook` skill (`skills/indicator-playbook/SKILL.md`,
  `allowed-tools: compute_technical_indicators, detect_chart_patterns`).

---

## detect_patterns (candlestick pattern detection)

**Agent-facing tool name:** `detect_chart_patterns` (wraps `_detect_chart_patterns`)

**Purpose:** Scans an OHLCV history for classic single-, two-, and three-candle reversal/continuation
patterns (doji, engulfing, hammer, shooting star, morning/evening star, three white
soldiers/black crows) so the agent can cite concrete pattern evidence ("a bullish engulfing formed
on 2026-08-01") instead of describing price action vaguely.

**Why built this way:** Implemented as pure vectorized pandas/numpy boolean masks over the whole
`Open/High/Low/Close` series (no candlestick library, no bar-by-bar loop) — each pattern is one
boolean condition (or a conjunction using `.shift(1)`/`.shift(2)` for multi-day patterns) applied
across the entire DataFrame at once, then the True positions are turned into `{pattern, date,
direction, strength}` dicts. This is fast and simple but purely shape-based: patterns are flagged
from candle geometry alone, with **no trend-context filter** (e.g. a "hammer" here does not require
a preceding downtrend, nor does "shooting star" require a preceding uptrend, even though textbook
definitions do) — so results should be read as candidate shapes, not confirmed reversal signals.
Requires at least 3 bars (`len(df) < 3` returns `[]` immediately, since the 3-candle patterns need
two prior bars). All detected matches across the whole input window are returned, sorted
most-recent-first (`patterns.sort(key=lambda x: x["date"], reverse=True)`); the agent wrapper then
truncates to the 10 most recent.

**Math (per pattern, using `body = |Close - Open|`, `range = High - Low`, `upper_shadow = High -
max(Open, Close)`, `lower_shadow = min(Open, Close) - Low`):**
- **Doji** — `body < 0.05 * range`. Direction: neutral. Strength 1.
- **Engulfing** — bullish: prior candle red (`Open[-1] > Close[-1]`), current candle green
  (`Open < Close`), and current body engulfs prior body (`Open <= Close[-1]` and `Close >=
  Open[-1]`). Bearish is the mirror image. Strength 2.
- **Hammer** — `lower_shadow > 2*body` and `upper_shadow < 0.5*body` and `Close > Open`
  (bullish). Strength 2.
- **Shooting star** — mirror of hammer: `upper_shadow > 2*body`, `lower_shadow < 0.5*body`,
  `Close < Open` (bearish). Strength 2.
- **Morning star** (3-candle bullish reversal) — 2 bars ago closed red (`Close[-2] < Open[-2]`),
  1 bar ago had a small body (`body[-1] < 0.3 * body[-2]`), today closes green and above the
  midpoint of the first candle's body: `Close > Open > Close` today and `Close > (Open[-2] +
  Close[-2]) / 2`. Strength 3.
- **Evening star** — mirror bearish version (2 bars ago green, small middle body, today red and
  closing below the first candle's midpoint). Strength 3.
- **Three white soldiers** — three consecutive up days (`Close > Open` for bars 0, -1, -2) with
  strictly rising closes and opens (`Close > Close[-1] > Close[-2]`, `Open > Open[-1] >
  Open[-2]`) and no excessive body shrinkage (`body > 0.5 * body[-1]`). Strength 3.
- **Three black crows** — mirror bearish version (strictly falling closes/opens, three down days,
  same body-shrinkage guard). Strength 3.

**Usage:**
- `detect_patterns(df: pd.DataFrame) -> list[dict]` — returns a list of
  `{"pattern": str, "date": ISO date string, "direction": "bullish"|"bearish"|"neutral", "strength":
  int}`, most recent first.
- Agent tool `detect_chart_patterns(symbol: str)`: fetches 3 months of daily OHLCV, runs
  `detect_patterns`, and returns the 10 most recent matches as JSON.
  - Example call: `detect_chart_patterns(symbol="NVDA")`
- Referenced by the `indicator-playbook` skill alongside `compute_technical_indicators`.

---

## detect_support_resistance

**Agent-facing tool name:** `get_support_resistance` (wraps `_get_support_resistance`)

**Purpose:** Identifies recent price levels where the stock has historically found buyers (support)
or sellers (resistance), for setting stop-losses, targets, or breakout/breakdown levels.

**Why built this way:** Uses a **fractal/pivot** definition of local extrema rather than any peak
library: a bar's `Low` counts as a support pivot if it equals the centered rolling minimum over a
window *and* is strictly lower than both immediate neighbors (guards against flat plateaus of tied
lows all counting as separate pivots); resistance is the mirror on `High` with a rolling maximum.
The `window` (default 20) auto-shrinks for short histories (`window = len(df) // 2 or 1` when
`len(df) < window`) so the function degrades gracefully instead of returning nothing on a thin
dataset. Raw pivots are then passed through `_deduplicate_levels`, a simple greedy clustering pass
that walks the sorted levels and keeps a candidate only if it differs from every already-kept level
by more than 1% (`tolerance=0.01`), collapsing near-duplicate levels from adjacent swing points into
one.

**Math:**
- `local_min = (Low == rolling_min(Low, window, center=True)) & (Low.shift(1) > Low) & (Low.shift(-1) > Low)`
- `local_max = (High == rolling_max(High, window, center=True)) & (High.shift(1) < High) & (High.shift(-1) < High)`
- Deduplication: for a sorted list of levels, keep level `x` iff `min(|x - r| / r for r in kept) > 0.01` for all previously kept `r`.
- Output keeps only the **last 5** entries of each sorted (ascending) list — i.e. the five
  highest-valued support pivots and the five highest-valued resistance pivots found in the window,
  not necessarily the ones nearest the current price.

**Usage:**
- `detect_support_resistance(df: pd.DataFrame, window: int = 20) -> dict` — returns
  `{"support": [float, ...], "resistance": [float, ...], "current_price": float}` (current price
  rounded to 4 decimals, taken from the last `Close`).
- Agent tool `get_support_resistance(symbol: str)`: fetches 6 months of daily OHLCV and calls
  `detect_support_resistance` with the default 20-bar window.
  - Example call: `get_support_resistance(symbol="MSFT")`
- Not referenced by name in any `skills/*/SKILL.md` allowed-tools list at the time of writing.

---

## wilder_rsi

**Agent-facing tool name:** Not exposed as an agent tool (no `@tool` wrapper in `tools_registry.py`).
Used internally as a plain Python helper by `quantagent/tools/market_overview.py`,
`quantagent/tools/screener.py`, and `quantagent/tools/reports/stock_report.py`.

**Purpose:** Returns a single, fast RSI-14 float for a close-price series, for code paths that need
to rank or filter many symbols by RSI cheaply (screeners, market overview, report generation)
without needing the full `pandas-ta` DataFrame machinery or an OHLC frame.

**Why built this way:** `pandas-ta`'s own `rsi()` already defaults to Wilder/RMA smoothing (its
`mamode` default is `"rma"`), so this hand-rolled version isn't a different *formula* — it's a
lighter-weight, dependency-free path that takes just a `Close` `pandas.Series` (no `Open/High/Low/
Volume` required) and returns one rounded scalar rather than a whole indicator column, which is
cheaper to call in a tight per-symbol loop (as `screener.py` does across hundreds of tickers).
Implemented with `Series.ewm(alpha=1/length, adjust=False)`, which recursively equals Wilder's
smoothed moving average from the very first observation — note this differs slightly from the
textbook Wilder method, which seeds the first `length` periods with a simple average of gains/losses
before switching to recursive smoothing; the `ewm(adjust=False)` form here starts the recursion
immediately, so early-window values (before `length` bars have accumulated) will differ marginally
from a strict textbook implementation, though both converge to the same value as more data accumulates.
Edge cases handled explicitly: returns `None` if there isn't at least `length + 1` closes (insufficient
data), and returns `100.0` directly if the average loss is exactly zero (pure uptrend), avoiding a
division-by-zero in the RS ratio.

**Math:**
```
delta = Close.diff()
gain  = ewm(delta.clip(lower=0), alpha=1/length, adjust=False).mean()   # Wilder-style smoothed avg gain
loss  = ewm(-delta.clip(upper=0), alpha=1/length, adjust=False).mean()  # Wilder-style smoothed avg loss
RS    = last(gain) / last(loss)          # if last(loss) == 0 → RSI = 100.0
RSI   = 100 - 100 / (1 + RS)
```

**Usage:**
- `wilder_rsi(close: pd.Series, length: int = 14) -> float | None` — returns the latest RSI value
  in `[0, 100]` rounded to 4 decimals, or `None` if there isn't enough history.
- Not directly callable by the LLM agent; it surfaces indirectly through tools that call it, e.g.
  `_get_market_summary`/market breadth helpers, the technical screeners (`screen_technicals_tool`,
  `screen_oversold_tool`), and generated stock reports (`generate_report_tool` with
  `report_type="stock"`).

---

## generate_signals

**Agent-facing tool name:** Not exposed as an agent tool directly. Used internally by
`quantagent/tools/backtesting.py` (`run_backtest`), which itself is exposed as `run_backtest_tool`.

**Purpose:** Converts an OHLCV history into a day-by-day `1`/`-1`/`0` (buy/sell/hold) `Signal`
column for one of six built-in strategies, which the backtester then turns into simulated trades
and performance stats.

**Why built this way:** A simple `str -> handler` dispatch dict (`_STRATEGY_DISPATCH`), mirroring
the indicator dispatch pattern in this same file, so adding a new strategy is a matter of writing
one handler and registering it. Every handler is a stateless function of the whole DataFrame
(vectorized `np.where`, no incremental/stateful loop), which keeps them simple and fast. Each
handler also accepts an optional `params: dict[str, float] | None` and reads its own tunable
numbers out of it via `.get(key, <default>)` — e.g. `sma_crossover` reads `fast`/`slow`,
`rsi_mean_reversion` reads `length`/`oversold`/`overbought` — so callers that need to vary a
strategy's parameters (grid search, walk-forward optimization) can, while omitting `params`
entirely reproduces each strategy's original hardcoded defaults exactly (`buy_and_hold` has no
tunables and ignores whatever it's given). Unknown strategy names are logged and return an all-`0`
(hold) signal column rather than raising, so a bad strategy string degrades to a no-op instead of
crashing a backtest run.

**Math (per strategy, `Signal = 1` buy / `-1` sell / `0` hold unless noted; defaults shown, all
overridable via `params`):**
- **`sma_crossover`** — fast = SMA(`params.get("fast", 50)`), slow = SMA(`params.get("slow", 200)`);
  `Signal = 1 if fast > slow, -1 if fast < slow, else 0` (classic golden-cross/death-cross trend rule).
- **`ema_crossover`** — fast = EMA(`params.get("fast", 12)`), slow = EMA(`params.get("slow", 26)`)
  (the defaults are the same periods used as MACD's inputs); same `>`/`<` crossover logic as above.
- **`rsi_mean_reversion`** — RSI(`params.get("length", 14)`);
  `Signal = 1 if RSI < params.get("oversold", 30), -1 if RSI > params.get("overbought", 70), else 0`.
- **`macd_momentum`** — computes `pandas-ta` MACD(`params.get("fast", 12)`, `params.get("slow", 26)`,
  `params.get("signal", 9)`), which returns columns in the order
  `[MACD, MACDh (histogram), MACDs (signal)]`. The handler compares the MACD line (column 0) against
  the true signal line, looked up via `_macd_signal_column` — a small helper that finds the column
  named `MACDs_*` (falling back to positional index 2 if no such name exists), so it's correct
  regardless of the fast/slow/signal periods used. (An earlier version of this code compared against
  column index 1 — the histogram, `MACDh` — instead of the signal line; that has been fixed.)
- **`bollinger_breakout`** — Bollinger Bands(`params.get("length", 20)`, 2σ) via `pandas-ta`
  (`BBL`/`BBM`/`BBU` at columns 0/1/2 respectively — correctly indexed here);
  `Signal = 1 if Close > BBU, -1 if Close < BBL, else 0`.
- **`buy_and_hold`** — sets `Signal = 1` on only the first row; a static long baseline for comparison.
  Takes no tunable parameters.

**Usage:**
- `generate_signals(df: pd.DataFrame, strategy: str, params: dict[str, float] | None = None) ->
  pd.DataFrame` — returns a copy of `df` with an added `Signal` column (initialized to 0, then
  filled by the chosen strategy handler).
  - `strategy` values: `sma_crossover`, `ema_crossover`, `rsi_mean_reversion`, `macd_momentum`,
    `bollinger_breakout`, `buy_and_hold`.
  - `params`: optional per-strategy tunable overrides (see Math above); unrecognized keys are
    ignored, so passing a param a strategy doesn't use is harmless.
- Not directly agent-callable; reached through the `run_backtest_tool` agent tool (`symbol`,
  `strategy`, `period` — no `params` argument is exposed there, so agent-driven backtests always use
  each strategy's defaults) and internally by `optimize_parameters`/`run_walkforward` in
  `backtesting.py`, which do vary `params` per grid-search combination. Referenced by the
  `backtesting` and `strategy-patterns` skills (`skills/backtesting/SKILL.md`,
  `skills/strategy-patterns/SKILL.md`), which both instruct always running `buy_and_hold` as a
  baseline and requiring a candidate strategy to beat it on a risk-adjusted basis before
  recommending it.

---

## compute_correlation_matrix

**Agent-facing tool name:** Not exposed as an agent tool — no `@tool` wrapper references it in
`tools_registry.py`, and no other module in the codebase imports it either (it is exercised only by
`tests/unit/tools/test_technical.py`). Effectively dead code from the agent's perspective today.

**Purpose:** Would compute a pairwise Pearson correlation matrix of closing prices across a set of
symbols — the kind of thing useful for portfolio diversification or pair-trading candidate
screening — if it were wired up to a tool or another module.

**Why built this way:** A one-line wrapper around `pandas.DataFrame.corr()` on a DataFrame of
aligned `Close` series (one column per symbol) — no custom math, just index alignment plus
pandas's default Pearson correlation, rounded to 4 decimals for display.

**Math:** Standard Pearson correlation coefficient between each pair of `Close` series:
`corr(X, Y) = Cov(X, Y) / (σ_X * σ_Y)`, computed pairwise over the rows where both series have data
(pandas aligns by index and pairwise-drops NaNs by default).

**Usage:**
- `compute_correlation_matrix(dfs: dict[str, pd.DataFrame]) -> pd.DataFrame` — `dfs` maps symbol to
  its OHLCV DataFrame; returns a symbol × symbol correlation DataFrame rounded to 4 decimals.
- Not callable by the LLM agent in the current build; would need a `@tool` wrapper (e.g. alongside
  `compare_peers`/`_compare_peers` in `tools_registry.py`) to be reachable.

---

## summarize_technicals

**Agent-facing tool name:** Not exposed as an agent tool directly. Used internally by
`quantagent/tools/reports/stock_report.py` and `quantagent/tools/reports/sector_report.py`, which
are reachable through the agent's `generate_report_tool` (`report_type="stock"` or `"sector"`).

**Purpose:** Produces one compact "technical snapshot" dict — trend, momentum, volatility, volume —
summarizing a symbol's technical posture in a handful of numbers, meant to be dropped straight into
a generated report or agent response rather than making the LLM read a full indicator DataFrame.

**Why built this way:** Recomputes each needed `pandas-ta` indicator once (`sma` at 20/50/200,
`rsi` at 14, `macd`, `bbands` at 20, `atr` at 14, `adx` at 14) with `append=False` so nothing is
mutated on the caller's DataFrame, then reduces each to its latest scalar value via small private
`_summarize_*` helpers. Requires at least 50 bars up front (`len(df) < 50` returns
`{"error": "Insufficient data (need >= 50 bars)"}`) since the longest input (SMA-200) needs
substantially more than that to be meaningful — this is a soft floor, not a hard requirement for
SMA-200 itself, so `sma200`/`above_sma200` can still legitimately be `None` if the caller has fewer
than 200 bars even after passing the 50-bar gate.

**Math:**
- **Trend** — latest SMA(20)/SMA(50)/SMA(200); `above_sma200 = Close > SMA(200)` (`None` if SMA-200
  unavailable).
- **Momentum** — latest RSI(14) rounded to 2 decimals; `macd_signal = "bullish" if MACD_line >
  signal_line else "bearish"`, where `signal_line` is looked up via the same `_macd_signal_column`
  helper used by `generate_signals`'s `macd_momentum` strategy (name-based lookup of the `MACDs_*`
  column, falling back to positional index 2). (An earlier version of this code compared against
  column index 1 — the histogram, `MACDh` — instead of the signal line; that has been fixed.)
- **Volatility** — `bb_position = (Close - BBL) / (BBU - BBL)` (guarded against a zero-width band);
  latest ATR(14); latest ADX(14) (extracted via `_extract_adx_value`, which unwraps whichever
  column `pandas-ta`'s ADX DataFrame puts the scalar ADX value in for the most recent row).
- **Volume** — 20-day average volume (rounded to whole units) and latest single-day volume.

**Usage:**
- `summarize_technicals(df: pd.DataFrame) -> dict` — returns
  `{"price": float, "trend": {...}, "momentum": {...}, "volatility": {...}, "volume": {...}}`, or
  `{"error": "..."}` if fewer than 50 bars are supplied.
- Not directly agent-callable; surfaces through `generate_report_tool(report_type="stock", target=
  "<symbol>")` and `generate_report_tool(report_type="sector", target="<sector name>")`, referenced
  indirectly by the `report-generation` skill (`skills/report-generation/SKILL.md`).
