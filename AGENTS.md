# AGENTS.md — QuantAgent

## Development Workflow
- **Package Manager:** `uv` (never `pip`). Install: `uv sync`. Add dep: `uv add <pkg>`.
- **Lint:** `uv run ruff check . --fix`. **Typecheck:** `uv run mypy .`.
- **Test:** `uv run pytest`. **Run app:** `uv run quantagent`.
- Python 3.11+. Use `match`, `X | Y` unions, `asyncio.TaskGroup`.

## Project Overview

QuantAgent is a terminal UI quant analysis app built on Textual, deepagents + LangGraph,
pandas-ta / vectorbt, managed with uv.

| Module | Responsibility |
|---|---|
| `quantagent/tui/` | Textual UI — widgets, slash commands, config, layout |
| `quantagent/tools/` | Pure quant analysis functions (no agent, no TUI) |
| `quantagent/agent/` | LangGraph agent, skills resolution, tool wrappers, middleware |
| `quantagent/adapter/` | Typed event bridge between agent and TUI |

**The TUI never imports from `agent/` or `tools/`. The agent never imports from `tui/`.**
All coupling is through `adapter/events.py` and `AgentRunner`.

## Documentation

`docs/architecture.md` (technical spec) and `docs/product-spec.md` (features) must always
reflect the current implementation — no planned/future work. Update them whenever you
change module structure, tools, commands, or providers. All AI coding agents must read
and follow them.

## Skills System

Skills are **directories** under `skills/` with a `SKILL.md` (YAML frontmatter + Markdown)
and optional reference files. deepagents uses **progressive disclosure**: only `description`
is read at startup; full body is loaded on demand when matched.

**Precedence (last wins):** `<package>/skills/` < `~/.quantagent/skills/` < `--skills-dir`.

- `agent/skills.py` (`SkillResolver`) resolves paths only — does NOT parse SKILL.md bodies.
- `agent/prompts.py` contains persona only — no domain knowledge. Domain knowledge belongs in skills.

## Coding Conventions

- **Type-annotate everything.** `from __future__ import annotations` at top of every file.
- **Docstrings** (Google style) on all public functions.
- **No bare `except`.** No `print()` in library code — use `logging`.
- Line length: **100 chars**. Cognitive complexity: **< 5**.
- **Async:** I/O-bound → `async`. CPU-bound → sync (use `asyncio.to_thread()` if >100ms).
- **Pydantic:** Config and result types must be `BaseModel`. Use `frozen=True` for results.
- **Data:** OHLCV DataFrames use `DatetimeIndex` (UTC), columns `Open/High/Low/Close/Volume`.
  Monetary values in USD. Rates as decimals. Symbols uppercased at entry point.
- **Secrets** from `.env` via Pydantic Settings. No globals — use dependency injection.
- **mypy:** Prefer stubs over `ignore_missing_imports`. Use `# type: ignore[import-untyped]` per-line.

## Module-Specific Rules

### `skills/`
- Directory with `SKILL.md` (frontmatter: `name`, `description`, `allowed-tools`).
- `description` is the trigger: "Use this skill when the user asks about X or Y."
- Reference files must be explicitly mentioned in `SKILL.md`.

### `tui/`
- Widgets are `textual.Widget` subclasses. Communicate via `post_message`, not direct calls.
- No business logic in widgets. Slash commands in `tui/commands.py`.
- `SessionState` is the only shared mutable state.

### `tools/`
- No imports from `agent/`, `tui/`, or `adapter/`.
- Accept `provider: AbstractDataProvider` as first arg — never instantiate providers.
- Return typed Python objects, not strings. Round numerics to 4 decimal places.

### `agent/`
- `create_quant_agent()` is the only public API.
- Tool docstrings in `tools_registry.py` are the LLM's interface — keep precise.
- Middleware must be stateless between turns.

### `adapter/`
- `AgentEvent` types are append-only. Never rename/remove fields.
- `AgentRunner` never imports Textual types. Communicates via `asyncio.Queue`.

## Dependency Rules

| From \ To | `tui/` | `tools/` | `agent/` | `adapter/` | `skills/` |
|---|---|---|---|---|---|
| `tui/` | ✅ | ❌ | ❌ | ✅ events only | ❌ |
| `tools/` | ❌ | ✅ | ❌ | ❌ | ❌ |
| `agent/` | ❌ | ✅ | ✅ | ❌ | ✅ read paths only |
| `adapter/` | ✅ config+state | ❌ | ✅ | ✅ | ❌ |
| `main.py` | ✅ | ❌ | ❌ | ❌ | ❌ |

## Testing

- Unit: `tests/unit/<module>/test_<file>.py`. Integration: `tests/integration/`.
- Snapshot (TUI visual regression): `tests/snapshot/`.
- Use `pytest-asyncio`. Mock providers — never make real API calls.
- Backtest tests use deterministic synthetic OHLCV data (fixed seed).

## Error Handling

- **Provider errors:** catch in tool wrappers, return descriptive error string.
- **Skill loading errors:** log warning, skip bad skill, continue.
- **Agent errors:** catch in `AgentRunner.run_turn()`, emit `AgentError(retryable=True)`.
- **TUI errors:** log + `SystemNotification`. Never crash the app.
- **Unrecoverable:** fail fast in `main.py` before TUI launches.

## Definition of Done

Before considering a task complete, run and pass all of:

```bash
uv run ruff check . --fix          # linter
uv run mypy .                      # type checker
uv run pytest --cov=quantagent --cov-report=term-missing  # tests + coverage
```

Coverage must meet: tools/ ≥85%, agent/skills.py ≥95%, adapter/ ≥90%. Fix any new violations before finishing.

## Do Not

- Domain methodology in `prompts.py` — use skills.
- Parse `SKILL.md` content in Python — deepagents does this natively.
- Flat `.md` skill files — must be a directory with `SKILL.md` inside.
- `time.sleep()` — use `asyncio.sleep()`.
- Secrets in `config.toml` — use `~/.quantagent/.env`.
- Commit `.env`, `*.key`, `*.pem`, `*secret*`.
- `app.refresh()` from asyncio task — use `app.call_from_thread()`.
- Hardcode tickers, date ranges, or thresholds in tool logic.
- Edit `uv.lock` manually.
- Mutate frozen Pydantic models after creation.
