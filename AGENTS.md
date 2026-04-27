# AGENTS.md — QuantAgent

This file guides AI coding agents working on this codebase.
Read it fully before making any changes.

---

## Development Workflow
- **Package Manager:** Use [uv](https://github.com) for all operations.
- **Environment:** Run `uv venv` and `source .venv/bin/activate`.
- **Install Dependencies:** `uv sync`.
- **Linting & Formatting:** Use [Ruff](https://astral.sh). Run `uv run ruff check . --fix`.
- **Type Checking:** Use [Mypy](https://readthedocs.io). Run `uv run mypy .`.

---

## Project Overview

QuantAgent is a terminal UI quant analysis application built on:
- **Textual** for the interactive TUI
- **deepagents** + **LangGraph** as the agent runtime
- **deepagents skills** for composable, on-demand domain knowledge
- **pandas-ta** / **vectorbt** for quantitative analysis
- **uv** for Python dependency and environment management

The codebase is split into four concerns that must remain loosely coupled:

| Module | Responsibility |
|---|---|
| `quantagent/tui/` | Textual UI — widgets, slash commands, config, layout |
| `quantagent/tools/` | Pure quant analysis functions (no agent, no TUI) |
| `quantagent/agent/` | LangGraph agent, skills resolution, tool wrappers, middleware |
| `quantagent/adapter/` | Typed event bridge between agent and TUI |

**The TUI never imports from `agent/` or `tools/` directly.**
**The agent never imports from `tui/`.**
All coupling is through `adapter/events.py` and `AgentRunner`.

---

## Environment Setup

```bash
# Install uv if not present
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies
uv sync

# Run the app
uv run quantagent

# Run tests
uv run pytest

# Add a dependency
uv add <package>

# Add a dev dependency
uv add --dev <package>
```

Never use `pip install` directly. Always use `uv add` or edit `pyproject.toml`
and re-run `uv sync`.

Python version: **3.11+** (enforced in `pyproject.toml`). Use `match` statements,
`X | Y` union types, and `asyncio.TaskGroup` freely.

## Repository Layout

```
quantagent/
├── pyproject.toml          # Single source of truth for deps and project metadata
├── uv.lock                 # Committed lockfile — do not edit manually
├── .env.example            # Template for ~/.quantagent/.env
├── AGENTS.md               # This file
│
├── skills/                 # Built-in skill library (shipped with the package)
│   ├── backtesting/
│   │   ├── SKILL.md
│   │   └── strategy_templates.md
│   ├── data-sources/
│   │   ├── SKILL.md
│   │   └── field_reference.md
│   ├── risk-framework/
│   │   ├── SKILL.md
│   │   └── position_sizing.md
│   ├── indicator-playbook/
│   │   ├── SKILL.md
│   │   └── indicator_combos.md
│   └── strategy-patterns/
│       ├── SKILL.md
│       └── regime_matrix.md
│
└── quantagent/
    ├── main.py             # Typer CLI entrypoint
    ├── tui/                # Terminal UI
    ├── tools/              # Quant analysis functions
    ├── agent/              # LangGraph agent + skills + middleware
    └── adapter/            # Agent ↔ TUI bridge
```

---

## Skills System

QuantAgent uses deepagents' native skills mechanism rather than a single monolithic
system prompt. Understanding this is essential before touching anything in `agent/`.

### How it works

Skills are **directories** under `skills/`. Each contains a `SKILL.md` with YAML
frontmatter and Markdown content, plus optional supporting reference files.

deepagents uses **progressive disclosure**: at startup, the agent reads only the
`description` field from each `SKILL.md`'s frontmatter. When a user prompt arrives,
the agent decides which skills apply based on their descriptions alone, then reads
the full `SKILL.md` for matched skills. Nothing is pre-loaded into the system prompt.

```
skills/backtesting/
├── SKILL.md           ← frontmatter description read at startup; body read on demand
└── strategy_templates.md  ← referenced inside SKILL.md; read only when skill is active
```

### Source precedence (last wins, same-named skills)

```
<package>/skills/       ← built-in, lowest priority
~/.quantagent/skills/   ← user personal overrides
--skills-dir <path>     ← custom dir (CLI flag), highest priority
```

A user skill directory with the **same name** as a built-in replaces it entirely.
A user skill directory with a **new name** is appended as an additional skill.

### `SkillResolver` vs deepagents

`agent/skills.py` contains `SkillResolver`, which is responsible only for:
- Scanning skill directories across all sources
- Applying precedence (last wins)
- Filtering `disabled_skills`
- Returning a list of skill directory paths

It does **not** parse `SKILL.md` bodies or inject content into prompts.
deepagents handles all of that natively via `create_deep_agent(skills=[...])`.

### Base system prompt

`agent/prompts.py` contains only the agent's **persona and general reasoning approach**.
It does NOT contain domain knowledge — that lives in skill files.
Domain knowledge in `prompts.py` is a bug.

### Memory vs Skills

| | Skills | Memory (`QUANTAGENT.md`) |
|---|---|---|
| **Loading** | On demand — matched by description | Always injected at every turn |
| **Content** | Methodology, rules, frameworks | Portfolio, preferences, watchlist |
| **Format** | `SKILL.md` in named directory | Single Markdown file |
| **Layering** | Last-wins override | Appended via `QuantMemoryMiddleware` |

---

## Coding Conventions

### General
- **Type-annotate everything.** All function signatures must have full type hints.
  Use `from __future__ import annotations` at the top of every file.
- **Docstrings on all public functions.** One-line for simple functions;
  multi-line with Args/Returns for complex ones.
- **No bare `except`.** Always catch specific exceptions. Log unexpected ones.
- **No `print()` in library code.** Use `logging.getLogger(__name__)` instead.
  The TUI uses `SystemNotification` events for user-facing messages.
- Line length: **100 characters** (configured in `pyproject.toml` via ruff).

### Async
- All I/O-bound functions (data provider calls, file reads, DB operations) must be `async`.
- CPU-bound functions (indicator computation, backtest vectorization) are **synchronous**.
  If they become slow (>100ms), run in a thread pool via `asyncio.to_thread()`.
- Never call `asyncio.get_event_loop()` — use `asyncio.get_running_loop()`.

### Pydantic models
- All configuration and result types must be Pydantic `BaseModel` subclasses.
- Use `model_config = ConfigDict(frozen=True)` for result types (immutable after creation).
- Never use `dict` as a return type where a Pydantic model is more appropriate.

### Data conventions
- All OHLCV DataFrames must have a `DatetimeIndex` (UTC) and columns:
  `Open`, `High`, `Low`, `Close`, `Volume` (capitalized exactly).
- All monetary values are in USD unless explicitly noted.
- All rates (ROE, growth rate, etc.) are expressed as decimals (`0.15` not `15`).
- `symbol` arguments must be uppercased at the entry point (tool wrapper), never deeper.

### Type checking (mypy)
- **No broad `ignore_missing_imports`.** Prefer installing official stubs (e.g. `pandas-stubs`,
  `types-requests`) via `uv add --dev`. If stubs do not exist for a library, add an explicit
  `# type: ignore[import-untyped]` comment on the import line. Never add whole modules to
  `[[tool.mypy.overrides]] ignore_missing_imports` in `pyproject.toml`.

## Coding Standards
- **Naming:** Follow PEP 8. Use `snake_case` for functions/variables and `PascalCase` for classes.
- **Type Hints:** Required for all function signatures. Use `list[str]` instead of `List[str]`.
- **Async:** Use `async/await` for all I/O bound operations.
- **Docstrings:** Use Google Style docstrings for public modules.

## Rules & Boundaries
- **No Hardcoding:** All secrets must come from `.env` via Pydantic Settings.
- **No Global State:** Do not use `global` variables. Use dependency injection.
- **File Changes:** Keep changes small and incremental. Verify with tests before finishing.
---

## Module-Specific Rules

### `skills/`
- Every skill is a **directory** containing at minimum a `SKILL.md` file.
- `SKILL.md` must have valid YAML frontmatter with at minimum `name` and `description`.
- The `description` field is the agent's only signal for deciding whether to use the skill.
  Write it as a precise trigger: "Use this skill when the user asks about X or Y."
- Supporting files (templates, references) must be **referenced explicitly** inside `SKILL.md`
  so the agent knows they exist and when to read them.
- `SKILL.md` must be under 10 MB (deepagents hard limit).
- Do not put the same content in both a skill and `prompts.py`. Pick one.
- `allowed-tools` in frontmatter should list only tools the skill actually directs the agent to use.

### `tui/`
- Every widget is a standalone `textual.Widget` subclass with its own CSS class.
- Widget-to-widget communication uses Textual's message system (`post_message`), not direct calls.
- No business logic in widgets. Widgets only render state and emit events.
- All slash command handlers live in `tui/commands.py`. Never inline command logic in `app.py`.
- `SessionState` is the only shared mutable state. Pass it explicitly; do not use globals.

### `tools/`
- Tool functions must not import from `agent/`, `tui/`, or `adapter/`.
- Every function that calls a provider must accept `provider: AbstractDataProvider` as its
  first argument — never instantiate a provider inside a tool function.
- Tool functions return Python types (DataFrames, dicts, Pydantic models), not strings.
  String formatting for the LLM happens only in `agent/tools_registry.py`.
- Numeric outputs must be rounded to 4 decimal places before serialization.

### `agent/`
- `create_quant_agent()` is the only public API. Do not expose internal graph nodes.
- `agent/skills.py` (`SkillResolver`) handles path resolution only — it does not parse
  SKILL.md bodies. deepagents handles content loading.
- `agent/prompts.py` contains persona only — no domain methodology.
- Tool docstrings in `tools_registry.py` are the LLM's interface — keep them precise,
  concise, and include all valid enum values for enum-like arguments.
- Middleware must be stateless between turns (no instance variables mutated during a turn).

### `adapter/`
- `AgentEvent` types in `events.py` are append-only. Never rename or remove existing fields —
  this breaks the match statements in `app.py`. Add new event types at the bottom.
- `AgentRunner` must never import Textual types. It communicates exclusively via `asyncio.Queue`.
- `resolve_approval()` must be idempotent — calling it twice with the same `interrupt_id`
  must not raise.

---

## Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=quantagent --cov-report=term-missing

# Run a specific test file
uv run pytest tests/unit/agent/test_skills.py -v

# Run snapshot tests (TUI visual regression)
uv run pytest tests/snapshot/ --snapshot-update  # update snapshots
uv run pytest tests/snapshot/                    # assert against saved snapshots
```

### Test conventions
- **Unit tests** go in `tests/unit/<module>/test_<file>.py`.
- **Integration tests** go in `tests/integration/test_<scenario>.py`.
- **Snapshot tests** (Textual visual regression) go in `tests/snapshot/`.
- Use `pytest-asyncio` with `@pytest.mark.asyncio` for all async tests.
- Mock the data provider for all unit tests — never make real API calls in tests.
- Use `unittest.mock.AsyncMock` for async provider methods.
- Backtest tests must use deterministic synthetic OHLCV data (fixed random seed).
- Every `AgentEvent` type must have at least one construction test in `tests/unit/adapter/test_events.py`.
- Test file names must mirror source file names exactly.
- Always clean irrelevant tests if the implementation is changed

### Coverage requirements
- `tools/`: minimum 85% line coverage
- `agent/skills.py`: minimum 95% line coverage (resolution logic is critical)
- `adapter/`: minimum 90% line coverage
- `tui/widgets/`: snapshot tests required for every widget's default state

---

## Common Tasks

### Add a new built-in skill

1. Create a new directory under `skills/<skill-name>/`.
2. Write `skills/<skill-name>/SKILL.md` with valid frontmatter:
   - `name`: matches the directory name exactly
   - `description`: precise trigger phrasing ("Use this skill when...")
   - `allowed-tools`: comma-separated list of tool names the skill uses
3. Add any supporting reference files to the same directory and reference them in `SKILL.md`.
4. Verify `SkillResolver` discovers it: `uv run python -c "from quantagent.agent.skills import SkillResolver; print(SkillResolver().resolve().skill_names)"`.
5. Add test cases in `tests/unit/agent/test_skills.py`.

### Create a user skill override (for documentation/examples)

Document the process in `README.md`:
1. Create `~/.quantagent/skills/<skill-name>/SKILL.md` with the same `name` as a built-in.
2. Run `/skills reload` in the TUI (or restart).
3. The user's version replaces the built-in — confirmed by `/skills` command output.

### Add a new quant tool

1. Implement the raw function in the appropriate `tools/*.py` file.
   - Accept `provider: AbstractDataProvider` as first arg if it needs market data.
   - Return a typed Pydantic model or DataFrame, not a string.
2. Add a `@tool`-decorated async wrapper in `agent/tools_registry.py` inside `build_tool_registry()`.
   - The docstring is the LLM's only interface — make it precise.
   - Call the raw function with the captured `provider`.
   - Serialize the result to a string (JSON or markdown table).
3. Add the new tool to the `return [...]` list at the bottom of `build_tool_registry()`.
4. If the tool is relevant to an existing skill, add its name to that skill's `allowed-tools`.
5. Add unit tests for both the raw function and the tool wrapper.
6. If the tool is potentially slow or consequential, add its name to `config.approval_required`.

### Add a new slash command

1. Define `async def handle_<n>(args: list[str], app: QuantAgentApp)` in `tui/commands.py`.
2. Register a `SlashCommand(name=..., usage=..., description=..., handler=...)` in `REGISTRY`.
3. If the command mutates the skill set or model, call `app.runner.reload_skills()` or
   `app.runner.set_model()` — do not reach into `runner._agent` directly.
4. Update `/help` (auto-generated from `REGISTRY`).
5. Add a unit test in `tests/unit/tui/test_commands.py`.

### Add a new data provider

1. Create `tools/providers/<n>.py` implementing `AbstractDataProvider`.
2. Add a case to `get_active_provider()` in `tools/providers/__init__.py`.
3. Add the provider name to `QuantAgentConfig.provider`'s `Literal` annotation.
4. Update the `data-sources` skill's `SKILL.md` capability matrix to include the new provider.
5. Add it to the `/provider` command's help text.
6. Add integration tests mocking the provider's HTTP layer (`respx` or `pytest-httpx`).

---

## Dependency Rules

| From \ To | `tui/` | `tools/` | `agent/` | `adapter/` | `skills/` |
|---|---|---|---|---|---|
| `tui/` | ✅ | ❌ | ❌ | ✅ events only | ❌ |
| `tools/` | ❌ | ✅ | ❌ | ❌ | ❌ |
| `agent/` | ❌ | ✅ | ✅ | ❌ | ✅ read paths only |
| `adapter/` | ✅ config+state | ❌ | ✅ | ✅ | ❌ |
| `main.py` | ✅ | ❌ | ❌ | ❌ | ❌ |

Skills directories are data, not code. `agent/skills.py` reads file paths from them.
No other module imports from or reads `skills/` directly.

---

## File Persistence

All user data is stored under `~/.quantagent/`. Never hardcode paths — always
resolve from `Path.home() / ".quantagent"`. The directory is created on first launch.

| Path | Owner | Description |
|---|---|---|
| `config.toml` | `tui/config.py` | Model, provider, disabled_skills, last thread |
| `.env` | `tui/config.py` | API keys — chmod 600 on creation |
| `QUANTAGENT.md` | User / agent | Always-on personal memory; injected every turn |
| `skills/` | User | Personal skill overrides and custom skills |
| `sessions.db` | `agent/sessions.py` | LangGraph SQLite checkpointer |
| `history.jsonl` | `tui/widgets/chat_input.py` | Input history for arrow-key recall |

---

## Error Handling Philosophy

- **Data provider errors** (network failure, bad symbol, rate limit): catch at the tool
  wrapper level in `tools_registry.py`, return a descriptive error string so the agent
  can handle gracefully (e.g. "Error: rate limit exceeded. Try again in 60s.").
- **Skill loading errors** (malformed frontmatter, missing SKILL.md): log a warning via
  `logger.warning`, skip the bad skill, continue with remaining skills. Never crash on
  a bad skill file.
- **Agent errors** (LLM failure, timeout, graph error): caught in `AgentRunner.run_turn()`,
  emitted as `AgentError(retryable=True)`. Never propagate to the Textual event loop.
- **TUI errors** (widget rendering, config parse): log with `logging`, show a
  `SystemNotification`. Never crash the app.
- **Unrecoverable errors** (missing `.env`, wrong Python version): fail fast at startup
  in `main.py` with a clear error message before the TUI launches.

---

## Do Not

- Do not put domain methodology (backtesting rules, indicator guides) in `prompts.py` — use skills.
- Do not parse `SKILL.md` content in Python code — deepagents does this natively.
- Do not add a new skill as a flat `.md` file — it must be a directory with `SKILL.md` inside.
- Do not use `time.sleep()` anywhere — use `asyncio.sleep()`.
- Do not store secrets in `config.toml` — always use `~/.quantagent/.env`.
- Do not commit `.env` files or any file matching `*.key`, `*.pem`, `*secret*`.
- Do not call `app.refresh()` from inside an asyncio task — use `app.call_from_thread()`.
- Do not hardcode ticker symbols, date ranges, or thresholds in tool logic — these must be parameters.
- Do not edit `uv.lock` manually.
- Do not use `pd.DataFrame.append()` (deprecated) — use `pd.concat()`.
- Do not mutate a `BacktestResult` or other frozen Pydantic model after creation.