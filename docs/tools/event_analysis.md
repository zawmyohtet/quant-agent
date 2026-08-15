# event_analysis.py

Analyzes how a stock has historically reacted to its earnings reports (gap,
day-1 move, post-event drift) and builds earnings calendars over a date range
for a universe. Source: `quantagent/tools/event_analysis.py`.

## analyze_earnings_impact

**Agent-facing tool name:** `analyze_earnings_impact`

**Purpose:** Quantifies how a stock has historically moved around its
earnings reports — overnight gap, full day-1 reaction, and short-term
post-earnings drift — to help size expectations ahead of an upcoming report.

**Why built this way:**

- Earnings dates from `provider.get_earnings_history` are matched to trading
  sessions in 2 years of daily OHLCV via `DatetimeIndex.searchsorted`, since
  an earnings release can occur before, during, or after market hours and
  its exact bar alignment varies by provider/company. The located "reaction"
  bar is the first bar at/after the earnings date.
- Events landing at the very start or end of the price history
  (`pos <= 0` or `pos >= len(df)`) are dropped — there is no prior close to
  compute a gap from, or no reaction bar to measure at all.
- The **day-1 close-to-close move** is treated as the primary reaction
  metric (drives `avg_abs_day1_move` and `positive_rate`) because it is
  robust to intraday timing ambiguity, unlike the gap alone.
- **5-day and 20-day drift** (`_DRIFT_WINDOWS = (5, 20)`) are computed as
  optional context, framed in the module docstring as
  post-earnings-announcement drift (PEAD) — a well-documented tendency for
  the initial reaction to continue over subsequent sessions. They are `None`
  when the window runs past the end of available price history, and
  `_mean_or_none` skips `None`s rather than treating them as zero when
  averaging.
- `quarters` defaults to 8 (roughly 2 years of quarterly reports) to balance
  a large enough sample against genuine regime drift in the company's
  reaction profile.

**Math:** for each historical report (`raw` from `get_earnings_history`,
`reaction` = the located bar, `prev_close` = prior session's close):

```
gap        = round(reaction.Open  / prev_close - 1, 4)
day1_move  = round(reaction.Close / prev_close - 1, 4)
drift_5d   = round(Close[reaction_pos + 5]  / reaction.Close - 1, 4)  # or None
drift_20d  = round(Close[reaction_pos + 20] / reaction.Close - 1, 4)  # or None
```

Aggregated across all `events_analyzed` valid events:

```
avg_abs_day1_move = mean(|day1_move| for each event)      # 4dp
positive_rate     = count(day1_move > 0) / events_analyzed  # 4dp — "win rate"
avg_gap           = mean(gap for each event)               # 4dp
avg_drift_5d      = mean of available drift_5d values (None if none present)
avg_drift_20d     = mean of available drift_20d values (None if none present)
```

Note: the only reaction-magnitude/"volatility" statistic computed is
`avg_abs_day1_move` (a mean absolute deviation of the day-1 move). The code
does **not** compute a standard deviation of the day-1 move or any other
explicit dispersion/volatility statistic — `avg_abs_day1_move` is the
closest proxy available for "how big does this stock's earnings reaction
typically run".

**Usage:**

```python
result = await analyze_earnings_impact(provider, "NVDA", quarters=8)
```

- `provider: AbstractDataProvider`
- `symbol: str` — stock ticker (upper-cased internally).
- `quarters: int = 8` — number of past reports to analyze.

Returns a dict:

```json
{
  "symbol": "NVDA",
  "events_analyzed": 8,
  "avg_abs_day1_move": 0.0642,
  "positive_rate": 0.625,
  "avg_gap": 0.0128,
  "avg_drift_5d": 0.0091,
  "avg_drift_20d": 0.0184,
  "events": [
    {
      "date": "2026-05-20",
      "eps_estimate": 0.71,
      "eps_actual": 0.76,
      "surprise_pct": 7.04,
      "gap": 0.0231,
      "day1_move": 0.0512,
      "drift_5d": 0.0187,
      "drift_20d": 0.0345
    }
  ]
}
```

If `provider.get_earnings_history` returns no data, the result is
`{"symbol": symbol, "events_analyzed": 0, "events": []}`.

## get_earnings_calendar_range

**Agent-facing tool name:** `get_earnings_calendar_range`

**Purpose:** Builds a forward-looking earnings calendar — which symbols in a
universe (or an explicit symbol list) report between a start and end date.

**Why built this way:**

- Per-symbol calendar fetches (`provider.get_earnings_calendar`) are cached
  for 12 hours (`_CALENDAR_TTL_SEC = 12 * 3600`) since upcoming-earnings
  dates don't change intraday and per-symbol calendar endpoints tend to be
  slow/rate-limited — a full-universe scan is explicitly documented as
  "slow on a cold cache".
- Fetch concurrency is bounded with `asyncio.Semaphore(8)` inside an
  `asyncio.TaskGroup`, parallelizing across symbols without overwhelming the
  provider.
- Progress is reported every 25 symbols fetched (`report_progress`) so a
  slow, cold-cache full-universe scan gives visible feedback.
- Per-symbol failures are caught, logged at debug level, and skipped
  (`except Exception`) rather than aborting the entire calendar build — one
  bad ticker shouldn't blank the whole result.
- Passing `symbols` explicitly bypasses the (slower) universe resolution
  entirely — `universe` is documented as ignored when `symbols` is given.

**Math:** no numeric formula; pure filter and sort:

- Collect all upcoming earnings events for the resolved symbol list (from
  cache or provider).
- Keep events where `start_date <= event.date[:10] <= end_date` — inclusive
  string comparison on `YYYY-MM-DD` dates (lexicographic ordering matches
  chronological ordering for ISO dates).
- Emit columns `symbol`, `date` (truncated to the first 10 chars,
  `YYYY-MM-DD`), `eps_estimate`, `quarter`.
- Sort ascending by `date`.

**Usage:**

```python
df = await get_earnings_calendar_range(
    provider,
    start_date="2026-08-15",
    end_date="2026-08-29",
    universe="sp500",
)
```

- `provider: AbstractDataProvider`
- `start_date: str` — range start, `YYYY-MM-DD`, inclusive.
- `end_date: str` — range end, `YYYY-MM-DD`, inclusive.
- `universe: str | None = None` — universe to scan (defaults to `sp500`
  inside the function); ignored when `symbols` is given.
- `symbols: list[str] | None = None` — explicit symbol list, bypassing
  universe resolution.

Returns a `pd.DataFrame` with columns `symbol, date, eps_estimate, quarter`,
sorted by `date`. Empty DataFrame if no reports fall in range.

The agent-facing tool (`_get_earnings_calendar_range` in
`tools_registry.py`) takes `symbols` as a comma-separated string (parsed via
`_parse_comma_symbols`) rather than a list, defaults `universe` to `"sp500"`,
runs under `_WARMUP_TIMEOUT_SEC`, and returns "No earnings reports in that
range." when the result is empty. Example agent call:

```
get_earnings_calendar_range(start_date="2026-08-15", end_date="2026-08-29", symbols="AAPL,MSFT,NVDA")
```
