# Report Generation

`quantagent/tools/reports/` turns the analytical primitives scattered across `tools/technical.py`,
`tools/market_overview.py`, `tools/sector_analysis.py`, `tools/portfolio.py`, `tools/screener.py`,
and the data provider into a handful of structured, renderable "reports" — a daily market brief, a
sector deep-dive, a single-stock deep-dive, a portfolio review, and a screening summary. Each
generator is a plain composition function: it calls several existing tool functions and packages
their outputs into an ordered list of `ReportSection`s, which `base.py` renders through shared
Jinja2 templates into Markdown or a self-contained HTML page.

The layer leans on one deliberate design pattern, `safe_section` (`_shared.py`), to keep a report
useful even when part of its data is unavailable: each section's builder coroutine is wrapped so
that an exception downgrades *just that section* to a `_Data unavailable (...)._` placeholder
instead of aborting the whole report. A report with five sections and one flaky data source still
renders four good sections and one honest error note, rather than failing outright.

Rendered reports are written to disk under `~/.quantagent/reports/` (`reports_dir()` in
`quantagent/tools/_paths.py`, overridable via the `QUANTAGENT_HOME` env var), as either
`<slug>-<timestamp>.md` or `<slug>-<timestamp>.html`.

There are two ways a report gets generated:

1. **Agent-mediated** — the LLM calls the `generate_report_tool` `@tool` (registered in
   `quantagent/agent/tools_registry.py`), which dispatches to the right generator, saves the file,
   and returns a preview to the model.
2. **Deterministic slash-command bypass** — per `docs/architecture.md` §5.3, `/stock <SYMBOL>
   report`, `/market report`, and `/sector <name> report` call the matching `reports/` generator
   *directly from `quantagent/tui/commands.py`*, with no LLM turn involved at all. This is the
   fast, cheap, "just build the file" path. Screening reports get the same treatment via `/screen
   ... report`. There is currently no deterministic slash-command form for portfolio reports — they
   are reachable only through the agent-mediated path (`/report portfolio <symbols>`, which still
   round-trips through the LLM, or a direct `generate_report_tool` call).

## Report / ReportSection / ReportConfig models

Defined in `quantagent/tools/reports/base.py`. All three are frozen (immutable) Pydantic models.

- **`ReportConfig`** — options that steer a generator's behavior. Fields: `title: str = ""`
  (overrides the generator's default auto-title when non-empty), `format: str = "markdown"`
  (`"markdown"` or `"html"` — informational; the actual output format is determined by which
  export function the caller invokes), `date_range: str = "1y"` (used by `stock_report.py` for the
  OHLCV lookback window), `benchmark: str = "SPY"` (used by `sector_report.py` and
  `portfolio_report.py` for relative-strength / risk comparisons). Every generator accepts
  `config: ReportConfig | None` and falls back to `ReportConfig()` when omitted.

- **`ReportSection`** — one section of a report: `title: str`, `content: str = ""` (raw Markdown
  prose, rendered as-is), `tables: list[pd.DataFrame] = []` (rendered separately, after the
  content). `arbitrary_types_allowed=True` lets the model hold `pd.DataFrame` fields directly.

- **`Report`** — the whole document: `title: str`, `generated_at: datetime` (defaults to
  `datetime.now(UTC)`), `sections: list[ReportSection] = []`, `metadata: dict[str, Any] = {}` (each
  generator stamps a `type` key here, e.g. `{"type": "stock", "symbol": "AAPL"}`, plus type-specific
  extras like `sector` or `symbols`).

**Rendering mechanics.** `_template_context(report)` flattens a `Report` into a plain dict:
`title`, `generated_at` formatted as `"%Y-%m-%d %H:%M UTC"`, `metadata`, and a `sections` list where
each `ReportSection` becomes `{title, content, tables_md}` — `tables_md` is each DataFrame run
through `df_to_markdown()` (a GitHub-style pipe table, no index, capped at 30 rows with an
"... N more rows omitted." footer; empty frames render as `_No data._`; floats are formatted to 4
decimal places with trailing zeros stripped).

- `render_markdown(report)` loads `templates/report.md.j2` from a Jinja2
  `Environment(FileSystemLoader(...), trim_blocks=True, lstrip_blocks=True)` and renders the
  context directly — the template just walks `sections`, printing `## {title}`, the raw
  `content`, then each pre-rendered `tables_md` entry.
- `render_html(report)` additionally runs each section's `content` + `tables_md` through
  `MarkdownIt("commonmark", {"html": False}).enable("table")` to produce a `section.html` string,
  then renders `templates/report.html.j2` (a self-contained page: `<title>`, inline `<style>` with
  `color-scheme: light dark` for automatic dark-mode, one `<h2>`/`<section>` per report section).
  The Jinja `Environment` itself uses `select_autoescape(["html"])`, but the HTML template embeds
  pre-rendered content via `{{ section.html | safe }}` (markdown-it output is trusted since it's
  produced from the report's own content, not raw user input).

**Export.** `export_report_markdown(report, path)` and `export_report_html(report, path)` both
`path.parent.mkdir(parents=True, exist_ok=True)` then `path.write_text(...)` the corresponding
render function's output. Callers (the `generate_report_tool` and the TUI's `_run_report_det`)
are responsible for choosing `path` — by convention
`reports_dir() / f"{slug}-{timestamp}.{md|html}"` under `~/.quantagent/reports/`.

## safe_section (graceful degradation)

`quantagent/tools/reports/_shared.py` defines the pattern every generator (except
`screening_report.py`, which has nothing to degrade — see below) uses to assemble sections whose
underlying data call might fail:

```python
async def safe_section(title: str, builder: Coroutine[Any, Any, ReportSection]) -> ReportSection:
    report_progress(f"building report section: {title}…")
    try:
        return await builder
    except Exception as exc:
        logger.warning("Report section '%s' failed: %s", title, exc)
        return ReportSection(title=title, content=f"_Data unavailable ({exc})._")
```

Mechanically: the caller passes an **already-created coroutine** (e.g.
`safe_section("Sector Performance", _sector_section(provider))` — note `_sector_section(provider)`
is called eagerly to produce the coroutine object, then handed to `safe_section`, which is the one
that actually `await`s it). `safe_section` reports TUI progress, awaits the coroutine inside a
broad `except Exception`, and on failure logs a warning and returns a fresh `ReportSection` with
the *same title* the section was supposed to have but with placeholder content
`_Data unavailable (<exception message>)._` (italicized Markdown) instead of raising. Because every
section in a report's `sections` list is built independently — sections that don't need
`safe_section` (cheap, synchronous, or already-fetched data) are built directly — one section's
data-provider timeout, missing cache, or bad symbol never prevents the other sections, or the
`Report` object itself, from being constructed and rendered. The report still gets a title, a
timestamp, and every other working section; only the failed one degrades in place.

`_shared.py` also has `dict_lines(data, keys=None)`, a small formatter used throughout the
generators to turn a `dict` into Markdown bullet lines (`- **Key Label:** value`, snake_case keys
title-cased), with a `_fmt` helper that formats floats to 4 decimals, joins dict values as
`k=v` pairs, and joins lists with commas (or `"—"` if empty).

## generate_market_daily

`quantagent/tools/reports/market_report.py`

```python
async def generate_market_daily(
    provider: AbstractDataProvider,
    config: ReportConfig | None = None,
) -> Report
```

**Purpose.** The daily market brief: regime, timing, breadth, sentiment, sector performance/
rotation, and top movers, all off one `get_market_summary` call plus a few extra sector/mover
fetches.

**Why built this way.** Most of the report (`Market Overview`, `Regime & Exposure`, `Timing
Signals`, `Breadth`, `Sentiment`) is derived from a single upfront `get_market_summary(provider)`
call and built synchronously with plain helper functions (`_overview_section`, `_regime_section`,
`_timing_section`, `_breadth_section`) — these aren't wrapped in `safe_section` because if the one
summary call fails the whole report can't be built anyway (it's awaited unguarded before section
assembly starts). The remaining three sections each need their *own* separate calls
(sector ranking, rotation detection, top movers) and are individually `safe_section`-wrapped so a
failure in, say, sector rotation detection doesn't take down the sections that already succeeded.
`_movers_section` additionally checks `BreadthStore().is_warm("sp500")` first and returns a
"cache cold" placeholder instead of calling `get_top_movers` at all when the breadth cache isn't
warmed — keeping the brief itself on the fast path (per the docstring: "top movers ... only when
the breadth cache is warm — the brief itself stays fast-path").

**Sections assembled** (in order):
1. **Market Overview** — indices + key support/resistance levels, from
   `market_overview.get_market_summary` (`summary["indices"]`, `summary["key_levels"]`).
2. **Market Regime & Exposure** — regime label/score/confidence, recommended exposure range, trend/
   volatility components, from `summary["regime"]` and `summary["recommended_exposure"]`.
3. **Timing Signals** — distribution-day count/signal, follow-through-day status, from
   `summary["timing"]`.
4. **Breadth** — universe/proxy and `% above N-day MA`, from `summary["breadth"]`.
5. **Sentiment** — raw `summary["sentiment"]` dict via `dict_lines`.
6. **Sector Performance** (`safe_section`) — `sector_analysis.get_sector_performance_ranked(provider)`.
7. **Sector Rotation** (`safe_section`) — `sector_analysis.detect_sector_rotation(provider)`.
8. **Top Movers** (`safe_section`) — `market_overview.get_top_movers(provider, direction="up"/"down", count=5)`,
   gated on `BreadthStore().is_warm("sp500")`.

**Usage.**
- Agent tool: `generate_report_tool(report_type="market")` (no `target` needed).
- Deterministic bypass: `/market report` in the TUI (`_handle_market` → `_run_report_det(app,
  "market", "", ...)`), which calls `_build_report` directly from `commands.py` with no LLM turn.
- Parameters: `provider` (injected), optional `config: ReportConfig`.
- Output: title defaults to `"Market Daily Brief — <YYYY-MM-DD>"`; `metadata={"type":
  "market_daily"}`; saved under `~/.quantagent/reports/market-<timestamp>.md` (or `.html`).

## generate_sector_report

`quantagent/tools/reports/sector_report.py`

```python
async def generate_sector_report(
    provider: AbstractDataProvider,
    sector: str,
    config: ReportConfig | None = None,
) -> Report
```

**Purpose.** Deep-dive on one GICS sector: performance rank, relative strength vs. a benchmark,
rotation role, ETF technicals, and industry breakdown.

**Why built this way.** `sector` is fuzzy-matched case-insensitively against `universe.SECTOR_ETFS`
via `_match_sector`, raising `ValueError` (with the valid-sector list) on no match — this happens
*before* any section is built, so a bad sector name fails fast rather than producing five degraded
sections. Every section thereafter is wrapped in `safe_section` since each depends on its own
provider/analysis call (sector rank tables, RS computation, rotation detection, per-ETF OHLCV +
technicals, and — per the docstring — industry classification which is "slow on a cold
classification cache" and therefore especially worth isolating).

**Sections assembled** (in order):
1. **Performance** — rank and full ranked table from
   `sector_analysis.get_sector_performance_ranked(provider)`, filtered to the matched sector's row
   for the `**Rank:** n of N` line.
2. **Relative Strength** — RS ratio/rank/trend for the sector from
   `sector_analysis.compute_sector_relative_strength(provider, benchmark=config.benchmark)`.
3. **Rotation Context** — calls `sector_analysis.detect_sector_rotation(provider)`, then determines
   the sector's role (`leading`/`lagging`/`improving`/`deteriorating`/`neutral`) by checking which
   of the returned `*_sectors` lists it appears in.
4. **Technical Summary** — resolves the sector's ETF via `universe.SECTOR_ETFS[sector]`, fetches
   1-year OHLCV with `provider.get_ohlcv(etf, period="1y")`, then
   `technical.summarize_technicals(df)`.
5. **Industry Breakdown** — `sector_analysis.get_industry_performance(provider, sector)`; renders
   `_No industry classification data available._` if the resulting DataFrame is empty.

**Usage.**
- Agent tool: `generate_report_tool(report_type="sector", target="<sector name>")`.
- Deterministic bypass: `/sector <name> report` (`_handle_sector` → `_run_report_det(app,
  "sector", sector, ...)`); errors with `Usage: /sector <name> report` if no sector is given.
- Parameters: `provider` (injected), `sector: str` (must match one of the 11 GICS sectors in
  `SECTOR_ETFS`, case-insensitive), optional `config: ReportConfig` (`benchmark` used for RS).
- Output: title defaults to `"<Sector> Sector Report — <YYYY-MM-DD>"`; `metadata={"type":
  "sector", "sector": matched}`; saved under `~/.quantagent/reports/sector-<name>-<timestamp>.md`.

## generate_stock_report

`quantagent/tools/reports/stock_report.py`

```python
async def generate_stock_report(
    provider: AbstractDataProvider,
    symbol: str,
    config: ReportConfig | None = None,
) -> Report
```

**Purpose.** A single-stock deep dive: quote/classification overview, technical read, fundamentals,
and recent news.

**Why built this way.** `symbol` is upper-cased up front; all four sections are `safe_section`-
wrapped since each hits the data provider independently (quote+classification, OHLCV, fundamentals,
news) and any one endpoint being unavailable for a given symbol shouldn't blank the whole report.
Per the docstring, DCF/F-Score valuation tools are deliberately *not* auto-run here — they need
inputs (FCF projections, balance-sheet history) that a generic report can't assume/guess, so
they're left to be called explicitly (by the agent or the user) rather than folded in.

**Sections assembled** (in order):
1. **Company Overview** — `provider.get_quote(symbol)` (price, change %, market cap, volume, 52-
   week high/low) and `provider.get_industry_classification(symbol)` (sector/industry), merged via
   `dict_lines`.
2. **Technical Analysis** — `provider.get_ohlcv(symbol, period=config.date_range)`, then
   `technical.summarize_technicals(df)`, `technical.detect_support_resistance(df)` (key levels),
   `technical.wilder_rsi(df["Close"])` (RSI-14), and
   `technical.detect_patterns(df.iloc[-30:])` (candlestick patterns over the last 30 bars — only
   the most recent 3 are listed, e.g. `"bullish_engulfing (2024-05-01)"`).
3. **Fundamental Analysis** — `provider.get_fundamentals(symbol)` via `dict_lines`.
4. **Recent News** — `provider.get_news(symbol, days=7)`, tabulated (date/title/source, first 10
   items) or `_No news in the last 7 days._` if empty.

**Usage.**
- Agent tool: `generate_report_tool(report_type="stock", target="<SYMBOL>")`.
- Deterministic bypass: `/stock <SYMBOL> report` (`_handle_stock` → `_run_report_det(app,
  "stock", symbols[0], ...)`).
- Parameters: `provider` (injected), `symbol: str` (upper-cased internally), optional `config:
  ReportConfig` (`date_range` sets the OHLCV lookback, default `"1y"`).
- Output: title defaults to `"<SYMBOL> Deep Dive — <YYYY-MM-DD>"`; `metadata={"type": "stock",
  "symbol": symbol}`; saved under `~/.quantagent/reports/stock-<symbol>-<timestamp>.md`.

## generate_portfolio_report

`quantagent/tools/reports/portfolio_report.py`

```python
async def generate_portfolio_report(
    provider: AbstractDataProvider,
    symbols: list[str],
    weights: dict[str, float] | None = None,
    config: ReportConfig | None = None,
) -> Report
```

**Purpose.** A portfolio review: allocation, risk metrics vs. a benchmark, sector exposure, a
suggested max-Sharpe reallocation, and a Monte Carlo simulation.

**Why built this way.** Symbols are upper-cased and weights normalized to sum to 1 up front via
`_normalize_weights` (equal-weight when `weights` is omitted; raises `ValueError` if provided
weights sum to <= 0) — this happens before section assembly so a bad weights input fails fast. The
`Allocation` section is a pure local computation (no provider call, so no `safe_section` needed);
the other four each depend on a separate provider/analysis call (portfolio metrics, sector
classification, optimization, Monte Carlo simulation) and are `safe_section`-wrapped so, e.g., a
Monte Carlo failure doesn't blank out the risk metrics that already succeeded. The optimization
section explicitly labels its output "suggestion, not advice."

**Sections assembled** (in order):
1. **Allocation** — a DataFrame of `{symbol, weight}` built locally from the normalized
   `weight_map`, sorted descending by weight. No underlying tool call.
2. **Risk Metrics** (`safe_section`) —
   `portfolio.compute_portfolio_metrics(provider, weight_map, benchmark=config.benchmark)`.
3. **Sector Exposure** (`safe_section`) —
   `sector_analysis.classify_symbols(provider, list(weight_map))`, aggregated into weight-by-sector
   (unclassified symbols bucket into `"Unknown"`).
4. **Optimization Suggestion** (`safe_section`) —
   `portfolio.optimize_portfolio(provider, symbols, method="max_sharpe")`.
5. **Monte Carlo** (`safe_section`) — `portfolio.monte_carlo_simulation(provider, weight_map)`.

**Usage.**
- Agent tool: `generate_report_tool(report_type="portfolio", target="<comma-separated symbols>")`
  (symbols only — the tool wrapper's `_build_report` dispatch does not currently pass custom
  `weights`, so it always uses equal weighting).
- Deterministic bypass: **none.** Unlike stock/market/sector/screening, there is no `/portfolio
  ... report` slash command in `commands.py`; portfolio reports are reachable only through the
  agent-mediated `/report portfolio <symbols>` picker/prompt or a direct `generate_report_tool`
  call, both of which still go through an LLM turn.
- Parameters: `provider` (injected), `symbols: list[str]`, optional `weights: dict[str, float]`
  (normalized; equal-weight if omitted), optional `config: ReportConfig` (`benchmark` used for
  risk metrics).
- Output: title defaults to `"Portfolio Review — <YYYY-MM-DD>"`; `metadata={"type": "portfolio",
  "symbols": symbols}`; saved under `~/.quantagent/reports/portfolio-<symbols>-<timestamp>.md`.

## generate_screening_report

`quantagent/tools/reports/screening_report.py`

```python
async def generate_screening_report(
    provider: AbstractDataProvider,
    screen_type: str = "fundamental",
    criteria: dict[str, Any] | None = None,
    universe: str = "sp500",
    config: ReportConfig | None = None,
) -> Report
```

**Purpose.** Runs one screen from `tools/screener.py` and packages the matches as a report with
run parameters and a caution note.

**Why built this way.** This generator does *not* use `safe_section` — there's only one real data
call (`_run_screen`, dispatched by `screen_type`), and it's awaited directly, unguarded, before any
section is built; if it raises, the whole report generation fails (there's nothing partial to
degrade to — a screening report *is* its results). `_run_screen` itself raises `ValueError` for an
unrecognized `screen_type` with the list of valid types. The three sections are otherwise pure
local formatting: **Parameters** documents exactly what was run (so the report is self-describing
even out of context), **Results** renders the matches table or a "no matches" message, and
**Notes** is a static disclaimer reminding the reader that screen output is candidates, not advice,
and should be validated with a deep-dive and a market-regime check.

**Sections assembled** (in order):
1. **Parameters** — screen description (from `_SCREEN_DESCRIPTIONS`), universe, criteria (or
   `"defaults"`), and match count — built locally, no tool call.
2. **Results** — the screen's result DataFrame as a table, or `_No stocks matched._` if empty. Fed
   by whichever of these `tools/screener.py` functions `_run_screen` dispatches to based on
   `screen_type`:
   - `"fundamental"` → `screener.screen_stocks(provider, universe=universe, criteria=criteria, limit=50)`
   - `"technical"` → `screener.screen_by_technicals(provider, criteria or {}, universe=universe)`
   - `"vcp"` → `screener.screen_vcp_pattern(provider, universe=universe)`
   - `"breakout"` → `screener.screen_breakout_candidates(provider, universe=universe)`
   - `"oversold"` → `screener.screen_oversold_reversal(provider, universe=universe)`
3. **Notes** — static disclaimer text, no tool call.

**Usage.**
- Agent tool: `generate_report_tool(report_type="screening", target="<screen_type>",
  criteria="<json>", universe="<name>")` (`target` maps to `screen_type`, default
  `"fundamental"`; `criteria` is a JSON string parsed with `json.loads` when non-empty).
- Deterministic bypass: `/screen ... report` (`_handle_screen` → `_run_report_det(app,
  "screening", "fundamental", ...)`) — note the bypass always runs the default `"fundamental"`
  screen with default criteria on the `"sp500"` universe; free-text criteria and other screen
  types are only available through the agent-mediated path.
- Parameters: `provider` (injected), `screen_type: str = "fundamental"` (one of `fundamental |
  technical | vcp | breakout | oversold`), `criteria: dict | None`, `universe: str = "sp500"`,
  optional `config: ReportConfig`.
- Output: title defaults to `"Screening Report (<screen_type>) — <YYYY-MM-DD>"`;
  `metadata={"type": "screening", "screen_type": screen_type, "universe": universe}`; saved under
  `~/.quantagent/reports/screening-<screen_type>-<timestamp>.md`.
