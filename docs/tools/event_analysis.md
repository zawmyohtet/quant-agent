# Event Analysis Tools

`quantagent/tools/event_analysis.py`

Tools for analyzing how stocks react to earnings announcements and building earnings calendars. Earnings are the most important scheduled events for stocks — they can cause big price moves and create trading opportunities.

---

## analyze_earnings_impact

**Agent tool:** `analyze_earnings_impact`

Analyzes how a stock has historically reacted to its earnings reports — the overnight gap, the full day-1 move, and the short-term drift afterward.

### What It Does

Looks at the last 8 quarters (2 years) of earnings reports for a stock and measures:
- **Gap** — how much the stock gapped up or down at the open after the report
- **Day-1 move** — the full close-to-close move on the earnings day
- **5-day drift** — how much the stock continued to move in the 5 days after
- **20-day drift** — how much the stock continued to move in the 20 days after

This helps you understand:
- How volatile is this stock around earnings?
- Does it tend to gap in the direction of the surprise?
- Is there post-earnings drift (the reaction continues for days)?

### How It Works

1. **Get earnings history** — fetches the last 8 quarters of earnings dates and EPS data
2. **Match to price data** — aligns each earnings date to the corresponding trading day
3. **Calculate reactions** — for each earnings event:
   - Gap = (open on earnings day / previous close) - 1
   - Day-1 move = (close on earnings day / previous close) - 1
   - 5-day drift = (close 5 days later / close on earnings day) - 1
   - 20-day drift = (close 20 days later / close on earnings day) - 1
4. **Aggregate** — computes averages across all events

**Why day-1 move is primary:** The gap alone doesn't capture the full reaction — some stocks gap less at the open but continue moving during the day. The close-to-close move is more robust to intraday timing ambiguity.

**Post-earnings drift:** Also called PEAD (Post-Earnings-Announcement Drift), this is a well-documented phenomenon where stocks continue to drift in the direction of the earnings surprise for days or weeks after the announcement.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `symbol` | `str` | required | Stock ticker |
| `quarters` | `int` | `8` | Number of past reports to analyze |

### Returns

A dictionary with:
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

**Field explanations:**
- `avg_abs_day1_move` — average absolute value of day-1 moves (how volatile is this stock around earnings?)
- `positive_rate` — percentage of earnings that resulted in a positive day-1 move (the "win rate" for going long into earnings)
- `avg_gap` — average overnight gap
- `avg_drift_5d`, `avg_drift_20d` — average post-earnings drift

### Usage

**Python API:**
```python
result = await analyze_earnings_impact(provider, "NVDA", quarters=8)
```

**Agent tool:**
```
analyze_earnings_impact(symbol="NVDA", quarters=8)
```

### Design Notes

**No standard deviation:** The tool computes `avg_abs_day1_move` as the only measure of reaction magnitude, not a standard deviation. This is a mean absolute deviation, which is simpler and more robust to outliers.

**Missing data handling:** If the provider doesn't have earnings history data, the tool returns `{"symbol": symbol, "events_analyzed": 0, "events": []}` rather than raising an error.

**Dropped events:** Events that land at the very start or end of the price history are dropped — there's no prior close to compute a gap from, or no future data to measure drift.

---

## get_earnings_calendar_range

**Agent tool:** `get_earnings_calendar_range`

Builds a forward-looking earnings calendar — which stocks in a universe are reporting earnings between two dates.

### What It Does

Given a date range (e.g. the next 2 weeks), finds all stocks in a universe that are reporting earnings in that window. This is useful for:
- Planning trades around upcoming earnings
- Avoiding stocks with earnings during a critical period
- Identifying earnings plays

### How It Works

1. **Resolve universe** — gets the list of stocks to check (or uses an explicit symbol list)
2. **Fetch earnings calendars** — for each stock, fetches upcoming earnings dates
3. **Cache results** — caches each stock's calendar for 12 hours (earnings dates don't change intraday)
4. **Filter by date range** — keeps only events in the specified range
5. **Sort and return** — sorts by date and returns a DataFrame

**Slow on cold cache:** The first time you run this for a full universe (like S&P 500), it needs to fetch earnings calendars for 500+ stocks, which can take minutes. After that, results are cached for 12 hours, so subsequent runs are fast.

**Bounded concurrency:** Limits to 8 simultaneous requests to avoid hitting rate limits. Progress is reported every 25 symbols.

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `provider` | `AbstractDataProvider` | required | Your data provider |
| `start_date` | `str` | required | Range start (YYYY-MM-DD, inclusive) |
| `end_date` | `str` | required | Range end (YYYY-MM-DD, inclusive) |
| `universe` | `str \| None` | `None` | Universe to scan (ignored if `symbols` is given) |
| `symbols` | `list[str] \| None` | `None` | Explicit symbol list (bypasses universe resolution) |

### Returns

A DataFrame with columns:
- `symbol` — stock ticker
- `date` — earnings date (YYYY-MM-DD)
- `eps_estimate` — analyst consensus EPS estimate (if available)
- `quarter` — fiscal quarter (e.g. "Q1 2026")

Sorted by date (earliest first). Empty DataFrame if no reports fall in the range.

### Usage

**Python API:**
```python
df = await get_earnings_calendar_range(
    provider,
    start_date="2026-08-15",
    end_date="2026-08-29",
    universe="sp500"
)
```

**Agent tool:**
```
get_earnings_calendar_range(start_date="2026-08-15", end_date="2026-08-29", symbols="AAPL,MSFT,NVDA")
```

The agent tool takes `symbols` as a comma-separated string and defaults `universe` to "sp500". It uses an extended timeout due to the potential for slow cold-cache runs.

### Design Notes

**Graceful failure:** If a single stock's earnings calendar fails to fetch, it's logged and skipped rather than aborting the entire calendar build. One bad ticker shouldn't blank the whole result.

**Explicit symbols bypass universe:** If you pass an explicit `symbols` list, the `universe` parameter is ignored. This lets you check earnings for a custom watchlist without loading a full universe.

---

## Summary

These event analysis tools help you understand and plan around earnings announcements:

- **analyze_earnings_impact** — how does a stock typically react to earnings?
- **get_earnings_calendar_range** — which stocks are reporting in a date range?

Use these tools to:
- Understand a stock's historical earnings volatility before trading through an announcement
- Identify stocks with upcoming earnings that might create trading opportunities
- Build earnings calendars for your watchlist or universe
- Measure post-earnings drift to see if there's a pattern you can exploit

Remember: earnings are binary events — the stock can gap up or down significantly based on the results and guidance. Understanding a stock's historical earnings behavior helps you size positions appropriately and set realistic expectations.
