# QuantAgent — Architecture

> Technical reference for developers and AI coding agents. Describes the code as it exists today — not a plan for the future. Keep this file in sync with the code whenever you change module structure, tools, commands, providers, or skills.

## 1. What it is

QuantAgent is a terminal (TUI) app. A user chats with an AI agent that can fetch live market data, run technical and fundamental analysis, detect market-wide regime/breadth/sector conditions, backtest strategies, optimize portfolios, screen stocks, generate reports, run saved workflows, and track a trade journal — all inside one keyboard-driven terminal window. The agent is built on LangGraph + deepagents, exposes 61 tools, supports 3 market-data providers and several LLM providers, and persists everything the user needs under `~/.quantagent/`.

Current version: `0.1.4`.

## 2. Tech stack

| Layer | Technology |
|---|---|
| TUI | Textual (Python) |
| Agent runtime | LangGraph + deepagents (`create_deep_agent`) |
| LLM interface | LangChain `init_chat_model` — native providers (Anthropic, OpenAI, Google Gemini, OpenRouter) plus an OpenAI-compatible gateway pattern for z.ai and OpenCode Go |
| Market data | yfinance, Alpha Vantage, Polygon |
| Quant libraries | pandas-ta, vectorbt, scipy, statsmodels, numpy, pandas |
| Reports | jinja2 (templates), markdown-it-py |
| Persistence | aiosqlite (threads, breadth cache, trade journal), toml (config), pyyaml (custom workflows) |
| Env / deps / quality | uv, pydantic / pydantic-settings, ruff, mypy, pytest |

Note: `pyproject.toml` declares `requires-python = ">=3.12"`, but `AGENTS.md`, `ruff` (`target-version = "py311"`), and `mypy` (`python_version = "3.11"`) are all pinned to 3.11. This is a real inconsistency in the repo as of this writing — be aware of it rather than assuming one number is authoritative.

## 3. Four-layer architecture

```
┌─────────────┐      AgentEvent queue      ┌─────────────┐
│    TUI      │  ◄──────────────────────►  │   Adapter   │
│  (textual)  │   slash commands, state    │  (runner)   │
└─────────────┘                            └──────┬──────┘
                                                   │
                                            ┌──────┴──────┐
                                            │    Agent    │
                                            │ (LangGraph) │
                                            └──────┬──────┘
                                                   │
                                            ┌──────┴──────┐
                                            │    Tools    │
                                            │ (quant fns) │
                                            └──────┬──────┘
                                                   │
                                            ┌──────┴──────┐
                                            │  Providers  │
                                            │(market data)│
                                            └─────────────┘
```

**Dependency rules (enforced by convention, see `AGENTS.md`):**

| From \ To | `tui/` | `tools/` | `agent/` | `adapter/` | `skills/` |
|---|---|---|---|---|---|
| `tui/` | ✅ | ❌ | ❌ | ✅ events only | ❌ |
| `tools/` | ❌ | ✅ | ❌ | ❌ | ❌ |
| `agent/` | ❌ | ✅ | ✅ | ❌ | ✅ read paths only |
| `adapter/` | ✅ config+state | ❌ | ✅ | ✅ | ❌ |

All TUI ↔ agent coupling flows through `adapter/events.py` and `AgentRunner`. The TUI never imports from `agent/` or `tools/` directly (it does call `quantagent.tools.providers.get_active_provider` and read-only helpers like `quantagent.tools.workflows.list_workflows()` / `quantagent.tools.universe.list_universes()` for menu population — this is a narrow, intentional exception used only to populate picker menus, not to run analysis).

## 4. Module reference

### 4.1 `quantagent/tui/` — Terminal UI

| File | Role |
|---|---|
| `app.py` | Root `QuantAgentApp(App)`. Composes `MessageView`, `StatusBar`, `ChatInput`, and Textual's built-in `Footer`. Consumes the `AgentEvent` queue in `_consume_events`/`_handle_event` and dispatches by event type to widget methods. Renders an ASCII welcome banner on mount (full or compact depending on terminal width). `watch_theme` persists theme changes back to `config.toml`. `get_provider()` caches the active market-data provider, rebuilt when `config.provider` changes. |
| `app.tcss` | Textual stylesheet. |
| `config.py` | `QuantAgentConfig` (pydantic `BaseModel`) — see §6.3. Loads/saves `~/.quantagent/config.toml`; `load_dotenv_file()` loads `~/.quantagent/.env`. |
| `session_state.py` | `SessionState` dataclass — `config`, `thread_id`, `token_count`, `is_running`, `current_activity` (None / "thinking" / a tool name), `turn_started_at`. Also owns the SQLite thread-metadata store (`~/.quantagent/sessions.db`, joined against the LangGraph checkpointer's own `checkpoints` table so a thread only "exists" once it has real content). |
| `commands.py` | Slash-command `REGISTRY` — see §5 (full command table lives in `docs/product-spec.md`). |
| `_history.py` | Replays checkpointed LangGraph messages into `MessageView` when switching threads. |
| `widgets/` | `message_view.py` (virtualized chat history, max 50 DOM nodes), `chat_input.py` (multiline input + `/`-command autocomplete dropdown), `status_bar.py` (activity/model/provider/thread/tokens), `approval_dialog.py` (HITL modal), `thread_selector.py` (Ctrl+T modal), `help_screen.py` (F1 modal — commands by category + keybindings), `picker.py` (generic list-selection modal used by `/workflow`, `/report`, `/universe` when no argument is given). |

**Key principle:** widgets never contain business logic — they render state and emit messages.

### 4.2 `quantagent/adapter/` — Agent ↔ TUI bridge

| File | Role |
|---|---|
| `events.py` | Immutable `AgentEvent` dataclasses (append-only — never rename/remove a field): `AgentTextChunk(chunk)`, `ToolCallStarted(call_id, tool_name, args)`, `ToolCallCompleted(call_id, result, is_error=False)`, `ToolProgress(call_id, text)` — empty `call_id` means "most recent running tool", `AgentError(message, retryable=False)`, `SystemNotification(text)`, `ApprovalRequest(call_id, tool_name, args)`, `AgentTurnComplete()`. `ApprovalDecision(approved)` is a separate, non-`AgentEvent` value that travels TUI → runner. |
| `runner.py` | `AgentRunner` — thin facade owning the `asyncio.Queue[AgentEvent]`, the compiled agent graph, and the checkpointer. Public API: `start()`, `run_turn(user_message)`, `resolve_approval(approved)`, `load_history(thread_id)`, `delete_thread(thread_id)`, `cancel()`, `reload_skills()`, `set_model(model)` (recreates the agent — note the `/model` command does **not** call this; see §4.1/§5), `shutdown()`, `get_event_queue()`. |
| `_stream_processing.py` | Drives one `agent.astream(..., stream_mode=["messages", "updates"], subgraphs=True)` pass. `_ChunkParser` filters out subgraph chunks so nested-graph output never interleaves. `_UpdatesHandler` extracts `__interrupt__` payloads. `_MessageDispatcher` / `_AIMessageHandler` / `_ToolCallBufferManager` translate LangChain messages into `AgentEvent`s — a tool call is only emitted once its buffered name+args are complete. |
| `_interrupt_processing.py` | HITL interrupt resolution: `_process_single_interrupt` (single-action interrupt) and `_process_action_requests` (multi-action interrupt, using LangChain's `ApproveDecision`/`RejectDecision`) build the resume payload consumed by `AgentRunner._handle_interrupts`. |

### 4.3 `quantagent/agent/` — LangGraph agent

| File | Role |
|---|---|
| `graph.py` | `create_quant_agent(config, checkpointer, approval_callback=None)` — the only public API for building the agent. Wiring order: (1) `_create_chat_model(config)` — parses `config.model` as `"provider:model"`; if the provider is `zai` or `opencode`, it calls `init_chat_model(model=name, model_provider="openai", api_key=..., base_url=...)` (an OpenAI-compatible gateway, not a native LangChain provider); otherwise it calls `init_chat_model(name, model_provider=provider)` for native providers (anthropic, openai, google_genai, openrouter). (2) `build_tool_registry(config)`. (3) `SkillResolver(...).resolve()`. (4) `FilesystemBackend(root_dir=~/.quantagent)`. (5) middleware list, in order: `ErrorLoggingMiddleware()`, `ToolProgressMiddleware()`, `SummarizationMiddleware(token_threshold=80_000, model=model)`, then `ApprovalMiddleware(...)` appended only if `config.approval_required` is non-empty. (6) `create_deep_agent(...)` with `skills=resolved.skill_dirs`, `checkpointer`, `middleware`. |
| `tools_registry.py` | `build_tool_registry(config)` returns 61 LangChain `@tool`-wrapped functions (52 provider-bound + 9 provider-independent — see §4.4/§6.1 for the full list). Provider-bound tools are bare `async def _name(provider, ...)` functions wrapped by `_bind_provider(func, provider)`, which pre-binds the active provider via closure and synthesizes the real `inspect.Signature` so LangChain's schema inference exposes actual parameters (`symbol`, `period`, ...) instead of `*args, **kwargs`. Each tool's docstring is the LLM's only interface — it must document valid enum values and parameter semantics precisely. No `try/except` inside any wrapper — errors propagate to `ErrorLoggingMiddleware`. |
| `skills.py` | `SkillResolver` — discovers skill directories (any subdirectory containing a `SKILL.md`) from built-in → user → extra dirs, applying precedence (last wins for a same-named skill) and the `disabled_skills` filter. Only reads the `description:` frontmatter field (via a small manual parser, no YAML lib) for the `list_all()` helper — it never parses the rest of a SKILL.md body; that's deepagents' job via progressive disclosure at runtime. |
| `prompts.py` | `BASE_SYSTEM_PROMPT` — persona, reasoning standards, and output format (stance/conviction/levels) only. No domain methodology — that lives in `skills/`. |
| `sessions.py` | `get_checkpointer()` — `AsyncSqliteSaver` over `~/.quantagent/sessions.db`. `new_thread_id()` uses `uuid_utils.uuid7()`. |
| `studio.py` | `get_graph()` — no-arg factory for LangGraph Studio. Uses a separate `~/.quantagent/studio_sessions.db` and `approval_callback=None` (auto-approves everything, since Studio runs headless). |
| `middleware/` | See §4.3.1. |

#### 4.3.1 Middleware (execution order inside `create_quant_agent`)

1. **`ErrorLoggingMiddleware`** — wraps every tool call (`wrap_tool_call`/`awrap_tool_call`). Catches exceptions and returns an error `ToolMessage` to the LLM instead of crashing the turn; also detects `ToolMessage(status="error")` results the `ToolNode` already produced. Logs tool name, args, and error to `~/.quantagent/logs/errors.log` either way.
2. **`ToolProgressMiddleware`** — binds the active tool-call id via `utils/progress.py`'s context manager around each tool invocation, so a long-running tool can call `report_progress(text)` and have it routed to the correct `ToolProgress` event/TUI line.
3. **`SummarizationMiddleware(token_threshold=80_000, model=model)`** — if a rough token estimate (4 chars/token, summed message content length) exceeds the threshold, keeps the system message plus the last 10 messages and replaces everything in between with a placeholder message. Despite taking a `model` argument and its name, this is **not** LLM-driven summarization — it's a naive truncation; the stored `model` is never actually invoked.
4. **`ApprovalMiddleware`** (only added if `config.approval_required` is non-empty) — subclasses LangChain's `HumanInTheLoopMiddleware`; every tool name in `approval_required` triggers an interrupt.

All middleware must be stateless between turns.

### 4.4 `quantagent/tools/` — Pure quant functions

No imports from `agent/`, `tui/`, or `adapter/`. Functions accept `provider: AbstractDataProvider` as the first argument where they need market data — they never instantiate a provider themselves. Return typed Python objects (DataFrames, dicts, pydantic models), not strings; serialization to JSON/markdown happens only in `tools_registry.py`.

| File | Role |
|---|---|
| `_paths.py` | Shared `~/.quantagent/` path helpers: `quantagent_home()` (overridable via `QUANTAGENT_HOME` env var, used by tests), `cache_dir()`, `universes_dir()`, `workflows_dir()`, `reports_dir()`, `trades_db_path()`, `ensure_dir()`. Exists because `tools/` cannot import `tui/config.py` under the dependency rules. |
| `market_data.py` | Thin async pass-throughs to the active provider: `get_ohlcv`, `get_quote`, `get_fundamentals`, `get_earnings_calendar`, `get_news`, `search_symbols`, `get_sector_performance`, `get_economic_indicators`. |
| `technical.py` | `compute_indicators` (SMA/EMA/RSI/MACD/BBands/ATR/ADX/OBV/Stochastic/VWAP/Supertrend via a dispatch table), `detect_patterns` (Doji, Engulfing, Hammer, Shooting Star, Morning/Evening Star, Three White Soldiers/Black Crows), `detect_support_resistance`, `generate_signals` (SMA/EMA crossover, RSI mean reversion, MACD momentum, Bollinger breakout, buy-and-hold — all implemented), `compute_correlation_matrix`, `summarize_technicals`, `wilder_rsi`. |
| `fundamental.py` | `compute_dcf`, `score_piotroski_f`, `score_altman_z`, `peer_comparison`, `compute_magic_formula_rank`. The Magic Formula function exists but currently has no `@tool` wrapper in `tools_registry.py` — it is not agent-callable today. |
| `backtesting.py` | `run_backtest` (vectorbt-based), `run_walkforward`, `optimize_parameters` (grid search), `format_backtest_result`. Returns a frozen `BacktestResult` pydantic model. |
| `portfolio.py` | `optimize_portfolio` (max_sharpe / min_vol / risk_parity / equal_weight), `compute_portfolio_metrics` (beta, VaR 95/99, CVaR, tracking error, information ratio), `monte_carlo_simulation`. |
| `screener.py` | `screen_stocks`, `screen_by_fundamentals`, `screen_by_technicals`, `screen_combined`, `screen_vcp_pattern` (Minervini VCP), `screen_breakout_candidates`, `screen_oversold_reversal`. Screens run against a named universe (see `universe.py`) with batch data fetching, not a hardcoded symbol cap. |
| `universe.py` | Custom + built-in screening universes: `builtin_universe_symbols(name)` (Wikipedia-scraped, cached), `list_universes`, `create_universe`, `load_universe`, `delete_universe`, `get_universe_metadata`. Custom universes saved to `~/.quantagent/universes/<name>.json`. |
| `sector_analysis.py` | `get_sector_performance_ranked`, `get_industry_performance`, `classify_symbols`, `compute_sector_relative_strength`, `detect_sector_rotation`. `get_sector_etf_heatmap` and `compute_sector_correlation` also exist here but currently have no `@tool` wrapper. |
| `market_breadth.py` | The largest tools file. `count_distribution_days`, `detect_follow_through_day`, `compute_percent_above_ma`, `compute_advance_decline`, `compute_new_highs_lows`, `compute_breadth_thrust`, `detect_market_regime` (composite regime score + `exposure_band(score)` — an explicit equity-exposure recommendation), `compute_market_sentiment`. |
| `breadth_store.py` | `BreadthStore` — incremental SQLite-backed OHLCV cache at `~/.quantagent/cache/breadth.db` for universe-level breadth math. `is_warm()`, `warm_up(provider, universe)` (slow, one-time), `update(provider, universe)` (fast, incremental), `load_field(...)`. |
| `market_overview.py` | `get_market_summary` (one-shot indices + timing + breadth + regime rollup), `get_top_movers`, `get_most_active`, `generate_market_heatmap`. |
| `conviction.py` | `synthesize_conviction(provider)` — fuses regime, breadth, timing, sector rotation, and sentiment into one 0–100 score with a signal-convergence bonus, a stance label, and exposure guidance. |
| `workflows.py` | `Workflow`/`WorkflowStep`/`WorkflowResult` pydantic models; `run_workflow`; built-in factories `daily_market_check()`, `weekly_sector_review()`, `stock_research(symbol)`, `screening_pipeline(criteria)`, `portfolio_rebalance_review(symbols)`; `load_custom_workflow(name)` reads `~/.quantagent/workflows/<name>.yaml`; `list_workflows`, `get_workflow`, `workflow_requires_target`. |
| `reports/` | `base.py` (`Report`/`ReportSection`/`ReportConfig` pydantic models, Jinja2 rendering, `export_report_markdown`/`export_report_html`), `_shared.py` (`safe_section` — degrades a report section gracefully on failure), `market_report.py`, `sector_report.py`, `stock_report.py`, `portfolio_report.py`, `screening_report.py` — one generator function per report type. Saved reports live under `~/.quantagent/reports/`. |
| `trade_journal.py` | `TradeIdea` pydantic model with a forward-only lifecycle (`idea → entry_ready → active → partially_closed → closed / invalidated`, enforced by `_require_transition`). `log_trade_idea`, `update_trade_status`, `close_trade` (computes MAE/MFE from OHLCV over the holding period), `get_open_trades`, `get_trade_history`, `compute_trade_stats` (win rate, profit factor, expectancy, max consecutive losses). SQLite at `~/.quantagent/trades.db`. |
| `risk_gate.py` | `CircuitBreakerConfig`; `check_circuit_breaker()` (daily/weekly/monthly drawdown limits + consecutive-loss cooldown, reading realized P&L from the trade journal); `check_discipline_gate(provider, trade_id)` (blocks a trade idea missing a thesis/stop, or when the circuit breaker or market regime says reduce-only). Both only emit recommendations — neither touches a broker. |
| `pair_trading.py` | `find_cointegrated_pairs` (Engle-Granger scan within a universe/sector), `compute_spread_metrics` (hedge ratio, z-score, half-life, signal for a symbol pair). |
| `event_analysis.py` | `analyze_earnings_impact(provider, symbol, quarters=8)` (historical earnings-reaction stats), `get_earnings_calendar_range(provider, start_date, end_date, universe=..., symbols=...)`. |
| `cache.py` | `DataCache` — async `get`/`set`/`invalidate`/`clear`, transparently encoding/decoding pandas DataFrames alongside plain JSON. Backed by `~/.quantagent/cache/datacache.db`. |
| `providers/` | `base.py` — `AbstractDataProvider` (see §6.1). `yfinance_provider.py`, `alpha_vantage.py`, `polygon.py` — the three concrete providers. `__init__.py` — `get_active_provider(config)` dispatches on `config.provider`. |

### 4.5 `skills/` — Domain knowledge (data, not code)

12 built-in skill directories at the **repo root** `skills/` (not inside `quantagent/`), each a directory with a `SKILL.md` (YAML frontmatter: `name`, `description`, `license: MIT`, `metadata.author`/`version`, `allowed-tools`) plus optional reference files. deepagents reads only `description` at startup to decide relevance; the full body loads on demand when a user prompt matches.

| Skill | Covers |
|---|---|
| `advanced-screening/` | Value/momentum/oversold/breakout/VCP screens, custom universe management |
| `backtesting/` | Backtest methodology, Sharpe/drawdown interpretation, walk-forward validation. Has `strategy_templates.md`. |
| `data-sources/` | Which fields/data each provider supports. Has `field_reference.md`. |
| `earnings-analysis/` | Earnings-reaction behavior, calendars, post-earnings drift |
| `exposure-discipline/` | Position sizing, trading discipline, trade journal review, pre-entry risk gating |
| `indicator-playbook/` | Indicator interpretation and regime-appropriate indicator choice. Has `indicator_combos.md`. |
| `market-breadth/` | Advance/decline, new highs/lows, breadth thrust, distribution days, follow-through days |
| `market-regime/` | Bull/bear regime detection, equity exposure recommendation, market health overview |
| `pair-trading/` | Cointegration, hedge ratios, spread z-score/half-life |
| `report-generation/` | Generating and exporting reports |
| `risk-framework/` | Position sizing, stops, VaR, drawdown limits. Has `position_sizing.md`. |
| `sector-rotation/` | Sector leadership/laggards, relative strength, cycle positioning |
| `strategy-patterns/` | Trend-following vs mean-reversion system design per regime. Has `regime_matrix.md`. |

Users can override any built-in skill by placing a same-named directory under `~/.quantagent/skills/`; `--skills-dir` / `config.extra_skill_dirs` layers on top of that (last wins).

## 5. Data flow

### 5.1 Normal turn (agent-mediated)

1. User types text in `ChatInput` → `app.py` receives `ChatInput.Submitted`.
2. Text starting with `/` goes to `commands.dispatch()`; everything else goes to `_submit_user_message`, which adds the message to `MessageView`, sets `state.is_running = True`, and runs `runner.run_turn(text)` as an exclusive worker.
3. `AgentRunner._execute_turn` streams the agent via `astream(..., stream_mode=["messages", "updates"], subgraphs=True)`.
4. Chunks are translated into `AgentEvent`s by `_stream_processing.py` and placed on the `asyncio.Queue`.
5. `app.py._consume_events` pulls events and updates widgets in causal order (a single FIFO queue plus sequential chunk processing guarantees text streams before its tool call starts, tool calls complete before the turn ends, etc.).
6. `AgentTurnComplete` resets `state.is_running = False`.

### 5.2 Tool approval (HITL)

1. `ApprovalMiddleware` intercepts any tool call whose name is in `config.approval_required`.
2. LangGraph emits an `__interrupt__` update.
3. `AgentRunner._handle_interrupts` creates an `ApprovalRequest` event and awaits a future.
4. `app.py` shows `ApprovalDialog`; the user approves or rejects.
5. `runner.resolve_approval(bool)` resolves the future; the runner resumes the graph with `Command(resume=...)`.

### 5.3 Deterministic mode bypass (`quick` / `report` / `heatmap`)

Several slash commands support mode keywords that skip the LLM entirely and call `tools/` functions directly from `commands.py` — faster and cheaper than an agent turn, at the cost of no free-form reasoning:

- `/stock <SYMBOL> quick` → runs the `stock_research` workflow deterministically.
- `/stock <SYMBOL> report`, `/market report`, `/sector <name> report`, `/screen ... report` → call the matching `reports/` generator directly and save the file.
- `/market quick` → runs `daily_market_check`. `/sector quick` → `weekly_sector_review`. `/screen ... quick` → `screening_pipeline`.
- `/market heatmap [metric]` → sends an LLM prompt asking for a sector heatmap (this one is agent-mediated, unlike the other mode keywords).

Everything else — including `/backtest`, plain `/stock`/`/market`/`/sector`/`/screen` with no mode, `/workflow <name>` (when a name is given directly), `/report <type>` (when a type is given directly), `/journal`, and `/warm` — is agent-mediated: the handler calls `app._submit_user_message(...)` with a constructed prompt and runs a full LLM turn.

## 6. Key interfaces

### 6.1 `AbstractDataProvider` (`quantagent/tools/providers/base.py`)

Abstract methods every provider must implement:

```python
async def get_ohlcv(symbol, period="1y", interval="1d") -> pd.DataFrame   # DatetimeIndex UTC, columns Open/High/Low/Close/Volume
async def get_quote(symbol) -> dict
async def get_fundamentals(symbol) -> dict
async def search_symbols(query) -> list[dict]
async def get_news(symbol, days=7) -> list[dict]
async def get_earnings_calendar(symbol, lookahead_days=90) -> list[dict]
async def get_sector_performance() -> dict
async def get_economic_indicators() -> dict
```

Concrete default methods (overridable — a provider only needs to override these if it has a native, more efficient path):

```python
async def get_industry_classification(symbol) -> dict   # default: {symbol, sector: None, industry: None}
async def get_earnings_history(symbol, quarters=8) -> list[dict]   # default: []
async def get_batch_ohlcv(symbols, period, interval) -> dict[str, pd.DataFrame]   # default: bounded-concurrency loop (Semaphore(8)) over get_ohlcv
async def get_batch_quotes(symbols) -> dict[str, dict]   # default: bounded-concurrency loop over get_quote
```

Three concrete providers exist: `YFinanceProvider` (overrides `get_batch_ohlcv`, `get_industry_classification`, `get_earnings_history` with native/richer implementations), `AlphaVantageProvider`, `PolygonProvider` (both implement only the 8 abstract methods, falling back to the base-class defaults for the rest).

### 6.2 `AgentEvent` (adapter → TUI)

| Event | Payload | Rendered as |
|---|---|---|
| `AgentTextChunk` | `chunk: str` | Streaming markdown text |
| `ToolCallStarted` | `call_id, tool_name, args` | Collapsible tool call card |
| `ToolCallCompleted` | `call_id, result, is_error` | Filled result inside the card |
| `ToolProgress` | `call_id, text` | In-place update of the running tool's line |
| `AgentError` | `message, retryable` | Red error banner |
| `SystemNotification` | `text` | Grey system message |
| `ApprovalRequest` | `call_id, tool_name, args` | Modal dialog |
| `AgentTurnComplete` | — | Clears the running/activity state |

### 6.3 `QuantAgentConfig` (`quantagent/tui/config.py`)

```python
model: str = "anthropic:claude-sonnet-4-6"   # "provider:model_name"
provider: str = "yfinance"                    # "yfinance" | "alpha_vantage" | "polygon"
theme: str = "nord"                           # any registered Textual theme name
approval_required: list[str] = ["run_backtest_tool", "optimize_portfolio_tool", "delete_universe_tool"]
thread_id: str | None = None
zai_api_key: str | None = None                # excluded from the saved TOML — sourced from env/.env
zai_api_base: str = "https://api.z.ai/api/paas/v4/"
opencode_api_key: str | None = None           # excluded from the saved TOML — sourced from env/.env
opencode_api_base: str = "https://opencode.ai/zen/go/v1/"
extra_skill_dirs: list[str] = []
disabled_skills: list[str] = []
```

`QuantAgentConfig.load()` reads `~/.quantagent/config.toml` (or falls back to defaults), then applies `_with_env_overrides()`: pulls `ZAI_API_KEY`/`ZAI_API_BASE`/`OPENCODE_API_KEY`/`OPENCODE_API_BASE` from the environment via a separate `_GatewaySecrets(BaseSettings)`, and silently migrates two kinds of legacy values written by older versions — approval tool names (`run_backtest`→`run_backtest_tool`, `optimize_portfolio`→`optimize_portfolio_tool`) and theme names (`dark`→`textual-dark`, `light`→`textual-light`).

## 7. The `~/.quantagent/` file layout

Everything QuantAgent persists lives under `~/.quantagent/`. There is no first-run setup wizard — every file/directory is created lazily by whichever module needs it first.

| Path | Purpose |
|---|---|
| `config.toml` | `QuantAgentConfig` — model, provider, theme, approval list, skill overrides |
| `.env` | API keys (chmod 600), loaded with `override=False` |
| `skills/` | User overrides of built-in skills, same-named-directory convention |
| `sessions.db` | Thread history (LangGraph checkpoints) + thread metadata (`SessionState`) |
| `studio_sessions.db` | Separate thread store used only by LangGraph Studio (`agent/studio.py`) — not part of the normal app |
| `cache/datacache.db` | General `DataCache` (quotes, fundamentals, etc.) |
| `cache/breadth.db` | `BreadthStore` — incremental universe OHLCV for breadth math |
| `universes/<name>.json` | Custom screening universes |
| `workflows/<name>.yaml` | Custom user-defined workflows |
| `reports/` | Saved generated reports (Markdown/HTML) |
| `trades.db` | Trade journal |
| `logs/errors.log` | Rotating error log (tool failures, unhandled exceptions) |

## 8. Testing strategy

```
tests/
├── conftest.py
├── unit/
│   ├── tools/            # pure quant-logic tests + providers/ subpackage + _synthetic.py OHLCV helper
│   ├── agent/            # graph, sessions, skills, tools_registry + middleware/ subpackage
│   ├── tui/              # app, commands, config, session_state, widgets
│   ├── adapter/          # events, runner, stream/interrupt processing
│   └── utils/            # logging, progress
└── snapshot/             # Textual visual regression (pytest-textual-snapshot)
```

There is currently no `tests/integration/` directory, even though `AGENTS.md` describes an integration-test convention — all current coverage is unit + snapshot. Coverage gates per `AGENTS.md`: `tools/` ≥85%, `agent/skills.py` ≥95%, `adapter/` ≥90%.

## 9. Extension checklist

### Add a new data provider
1. Implement `AbstractDataProvider` in `tools/providers/<name>.py`; override the optional batch/classification methods only if you have a native path.
2. Register it in `tools/providers/__init__.py::get_active_provider`.
3. Update `skills/data-sources/SKILL.md` and `field_reference.md`.
4. Add tests under `tests/unit/tools/providers/`.

### Add a new quant tool
1. Implement the raw function in the appropriate `tools/*.py` file.
2. Add a `@tool` wrapper in `agent/tools_registry.py` (via `_bind_provider` if it needs provider access) with a precise docstring.
3. Add it to the returned list in `build_tool_registry`.
4. Add it to `allowed-tools` in the relevant skill(s).
5. Add unit tests for both the raw function and the wrapper.

### Add a new slash command
1. Write `async def _handle_<name>(app, args)` in `tui/commands.py`.
2. Register a `SlashCommand` entry in `REGISTRY` under the right category.
3. If it needs a deterministic (non-LLM) mode, follow the `modes=[...]` / `mode_min_args` pattern used by `/stock`, `/market`, `/sector`, `/screen`.
4. Add a unit test in `tests/unit/tui/test_commands.py`.

### Add a new built-in skill
1. Create `skills/<name>/SKILL.md` with frontmatter (`name`, `description`, `allowed-tools`) plus any reference files, referenced explicitly from the body.
2. Verify discovery: `uv run python -c "from quantagent.agent.skills import SkillResolver; print(SkillResolver().resolve().skill_names)"`.
3. Add tests in `tests/unit/agent/test_skills.py`.
