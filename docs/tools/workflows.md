# `quantagent/tools/workflows.py`

Workflow engine: orchestration only, no analytical math of its own. A
`Workflow` is an ordered list of `WorkflowStep`s, each naming a function from
a fixed registry (`STEP_REGISTRY`) plus the parameters to call it with.
`run_workflow` walks the steps in order, calling each registered tool
function with the shared `provider` and resolved parameters, and threads
each step's output forward so later steps can reference it via `$key` /
`$key.field` placeholders. Built-in workflows are just Python factory
functions that build one of these `Workflow` objects; custom workflows are
the same shape loaded from a user's YAML file.

---

## WorkflowStep / Workflow / WorkflowResult

**Agent-facing tool name:** Not exposed directly — these are the pydantic data
models that back `list_workflows_tool` and `run_workflow_tool`.

**Purpose:** `WorkflowStep` pins one registry tool name, its parameters, and
an `output_key` under which its result is stored. `Workflow` is an ordered
list of steps plus metadata (`name`, `description`, `estimated_duration`).
`WorkflowResult` is the record produced by a run: the workflow name, a
completion timestamp, a `step_results` dict keyed by each step's
`output_key`, and a human-readable `summary` string.

**Why built this way:** All three models are frozen (`ConfigDict(frozen=True)`)
so a `Workflow` definition and its results can't be mutated after
construction — a workflow is a value, not shared mutable state, which
matters because the same built-in factory can be called repeatedly (e.g. one
`stock_research` workflow object per symbol) without instances stepping on
each other. `WorkflowResult` allows `arbitrary_types_allowed` because
`step_results` can hold arbitrary tool outputs, including pandas DataFrames,
which pydantic doesn't validate natively.

**Math:** None. Pure data containers.

**Usage:** Constructed directly (`WorkflowStep(tool_name=..., parameters={...},
output_key=...)`, `Workflow(name=..., steps=[...])`) by the built-in factory
functions below and by `load_custom_workflow`. Not instantiated by end users
or agents directly.

---

## run_workflow

**Agent-facing tool name:** Not exposed directly — invoked internally by the
`run_workflow_tool` agent tool (`_run_workflow_tool` in
`quantagent/agent/tools_registry.py`), which wraps its `WorkflowResult` into
JSON.

**Purpose:** Executes a `Workflow`'s steps in sequence against a live data
provider, passing each step's output forward so subsequent steps can consume
it.

**Why built this way:** Steps run strictly sequentially and synchronously
with respect to each other (each step is `await`ed before the next begins) —
later steps in every built-in workflow depend on earlier ones only loosely
(they mostly reuse the same provider/market context rather than each other's
literal output), but the engine still guarantees ordering so step N+1 never
starts before step N's result is recorded. There is no per-step try/except:
if a step raises, `run_workflow` does not catch it — the exception
propagates out of `run_workflow` itself, aborting the whole workflow. This is
a deliberate simplicity choice: a workflow is meant to be a short, curated
pipeline (built-ins run in under a few minutes), so a broken step should fail
loudly rather than silently produce a partial, possibly misleading result.
Progress is reported per step via `report_progress` (step i/total, tool
name) so long-running workflows (e.g. `screening_pipeline` over an entire
universe) give visible feedback in the TUI.

**Math:** No computation here — this is pure control flow:
1. For each step, look up its `tool_name` in `STEP_REGISTRY`; raise
   `ValueError` immediately if the name isn't registered (with the full list
   of valid names in the error message).
2. Resolve the step's `parameters` dict against prior results: any string
   parameter value starting with `$` is treated as a reference — `$key`
   substitutes the entire prior output stored under `output_key == key`;
   `$key.field` looks up `field` inside that output (which must be a dict).
   An unresolvable reference raises `ValueError`.
3. Call the registered function as `await fn(provider, **params)`.
4. Store the result under `results[step.output_key]`, log a one-line
   description (`DataFrame (N rows)`, `dict (key1, key2, …)`, `list (N
   items)`, or the type name) into the running summary.
5. After all steps complete, return a `WorkflowResult` with the full
   `step_results` dict and the joined summary lines.

**Usage:**
```python
workflow = daily_market_check()
result = await run_workflow(provider, workflow)
result.step_results["conviction"]   # -> whatever synthesize_conviction returned
result.summary                       # "- market (get_market_summary): dict (...)\n- ..."
```

---

## STEP_REGISTRY

**Agent-facing tool name:** Not exposed — internal lookup table used by
`run_workflow` and consulted (via its error message) by callers debugging an
unknown `tool_name`.

**Purpose:** Maps the tool names usable inside a workflow step
(`step.tool_name`) to the actual async functions that implement them —
pulled from `market_data`, `market_overview`, `market_breadth`,
`sector_analysis`, `screener`, `portfolio`, `conviction`, `pair_trading`, and
`event_analysis`. Every entry has the signature
`async fn(provider, **kwargs) -> Any`.

**Why built this way:** A closed registry (rather than dynamic import/eval of
arbitrary function names) means custom YAML workflows can only invoke a
vetted, provider-first set of functions — this is what makes it safe to let
users supply their own workflow YAML without risking arbitrary code
execution.

**Math:** None — a static `dict[str, Callable]`.

**Usage:** Not called directly; reference this dict's keys when writing a
custom workflow YAML's `tool:` fields.

---

## daily_market_check

**Agent-facing tool name:** Reached through `run_workflow_tool` with
`name="daily_market_check"` (no target needed).

**Purpose:** The recurring "how does the market look today" routine: overall
market snapshot, sector performance, rotation signal, and a final conviction
score with exposure guidance.

**Why built this way:** Steps are ordered from broad to narrow context,
ending in the synthesis step: market summary and sector ranking establish
raw context first, sector rotation adds a directional read on top of that,
and `synthesize_conviction` is placed last because (per its own
documentation) it fuses regime/breadth/timing/rotation/sentiment signals —
running it last means it can act as a capstone score assuming the
provider's other cached/underlying data is already warm from the earlier
steps in the same request.

**Math:** No math in this file — it's a fixed 4-step chain:
1. `get_market_summary` -> `output_key="market"`
2. `get_sector_performance_ranked` -> `output_key="sectors"`
3. `detect_sector_rotation` -> `output_key="rotation"`
4. `synthesize_conviction` -> `output_key="conviction"`

None of the steps reference each other's outputs via `$key` — each is called
with no parameters (empty `parameters` dict), so they run independently in
sequence purely for combined reporting.

**Usage:** Takes no arguments — `daily_market_check() -> Workflow`. Typical
call:
```python
result = await run_workflow(provider, daily_market_check())
```
Estimated duration: "1-2 minutes".

---

## weekly_sector_review

**Agent-facing tool name:** Reached through `run_workflow_tool` with
`name="weekly_sector_review"` (no target needed).

**Purpose:** A slower, sector-focused cadence: rank sectors, quantify their
relative strength, and detect rotation between them.

**Why built this way:** Mirrors the sector portion of `daily_market_check`
but stands alone (without the broader market-summary/conviction steps) for
when the user only wants sector-level insight — e.g. a weekly cadence rather
than daily. Relative strength is computed after ranking so the rotation
detector has both the raw ranking and the RS view to draw on.

**Math:** No math in this file — a fixed 3-step chain, all parameterless:
1. `get_sector_performance_ranked` -> `output_key="ranking"`
2. `compute_sector_relative_strength` -> `output_key="rs"`
3. `detect_sector_rotation` -> `output_key="rotation"`

**Usage:** Takes no arguments — `weekly_sector_review() -> Workflow`.
Estimated duration: "1-2 minutes".

---

## stock_research

**Agent-facing tool name:** Reached through `run_workflow_tool` with
`name="stock_research"` and a required `target` (the symbol) —
`workflow_requires_target("stock_research")` is `True`.

**Purpose:** A quick single-symbol deep dive: current quote, fundamentals,
and recent news for one ticker.

**Why built this way:** Ordered cheapest/most-time-sensitive first (quote),
then slower-changing structural data (fundamentals), then qualitative
context (news) — a natural "what is it doing, what is it, why" reading
order for a human or agent consuming the combined result.

**Math:** No math — a fixed 3-step chain, all three parameterized with the
same `symbol`:
1. `get_quote(symbol=symbol)` -> `output_key="quote"`
2. `get_fundamentals(symbol=symbol)` -> `output_key="fundamentals"`
3. `get_news(symbol=symbol)` -> `output_key="news"`

**Usage:**
```python
workflow = stock_research("AAPL")
result = await run_workflow(provider, workflow)
```
`get_workflow("stock_research", target="aapl")` upper-cases the target
before calling the factory. Estimated duration: "under 1 minute".

---

## screening_pipeline

**Agent-facing tool name:** Reached through `run_workflow_tool` with
`name="screening_pipeline"` (no target; screen criteria aren't
parameterizable through `run_workflow_tool`'s `target` argument — the
built-in always screens with an empty criteria dict when invoked as an agent
tool).

**Purpose:** Establishes market regime context before running a fundamental
stock screen, so screen results can be read in light of whether the broader
market favors offense or defense.

**Why built this way:** Regime is checked first because screening criteria
(e.g. momentum vs. value tilts) are typically interpreted differently in a
risk-on vs. risk-off regime — putting `detect_market_regime` before
`screen_stocks` gives that context to whoever reads the combined result
without forcing the screen itself to depend on the regime output.

**Math:** No math — a fixed 2-step chain:
1. `detect_market_regime` -> `output_key="regime"` (no parameters)
2. `screen_stocks(criteria=criteria or {})` -> `output_key="candidates"`

**Usage:**
```python
workflow = screening_pipeline({"min_market_cap": 1e9, "rsi_max": 40})
result = await run_workflow(provider, workflow)
```
`criteria` defaults to `None` (treated as `{}`, i.e. an unfiltered screen).
Estimated duration: "2-4 minutes".

---

## portfolio_rebalance_review

**Agent-facing tool name:** Reached through `run_workflow_tool` with
`name="portfolio_rebalance_review"` and a required `target` (comma-separated
symbols) — `workflow_requires_target("portfolio_rebalance_review")` is
`True`.

**Purpose:** A portfolio health check: current risk metrics for an assumed
equal-weight holding, followed by max-Sharpe optimization suggestions for
the same symbol set.

**Why built this way:** Since the tool only receives a symbol list (not
actual position sizes), it assumes equal weighting (`1/len(symbols)`,
rounded to 4 decimals) as a neutral baseline for the risk-metrics step, then
runs true optimization afterward so the user can compare "if I were
equal-weight, here's my risk" against "here's what an optimizer would
recommend instead."

**Math:** No math in this file itself (the risk/optimization math lives in
`quantagent.tools.portfolio`) — a fixed 2-step chain:
1. `compute_portfolio_metrics(weights=weights)` -> `output_key="risk"`, where
   `weights = {SYM.upper(): round(1/len(symbols), 4) for sym in symbols}`
2. `optimize_portfolio(symbols=[s.upper() for s in symbols])` ->
   `output_key="optimization"`

**Usage:**
```python
workflow = portfolio_rebalance_review(["aapl", "msft", "googl"])
result = await run_workflow(provider, workflow)
```
`get_workflow("portfolio_rebalance_review", target="aapl,msft,googl")` splits
the comma-separated target and strips whitespace before calling the factory.
Estimated duration: "1-2 minutes".

---

## load_custom_workflow

**Agent-facing tool name:** Not exposed directly — called by `get_workflow`
as the fallback when `name` isn't a built-in, so it's reachable indirectly
through `run_workflow_tool`.

**Purpose:** Reads a user-authored workflow definition from
`~/.quantagent/workflows/<name>.yaml` and validates/parses it into a
`Workflow` object.

**Why built this way:** Lets users define their own routines without
touching Python — a YAML file with a `steps:` list of `{tool, parameters,
output_key}` entries, matched against the same `STEP_REGISTRY` used by
built-ins, so custom and built-in workflows execute through the identical
`run_workflow` code path (no special-casing at run time).

**Math:** No math — file I/O and validation:
1. Look up `<name>.yaml` under `workflows_dir()` (`~/.quantagent/workflows/`
   by default, overridable via `QUANTAGENT_HOME`); raise `ValueError` if the
   file doesn't exist.
2. `yaml.safe_load` the file.
3. Build a `WorkflowStep` per entry in `steps:`, reading `tool` ->
   `tool_name`, `parameters` (default `{}`), `output_key` (required, raises
   `KeyError`-derived failure if absent since it's accessed with `[...]`
   rather than `.get`).
4. Raise `ValueError` if the resulting step list is empty.
5. Return a `Workflow` using the YAML's `name` (defaulting to the filename
   stem), `description`, `estimated_duration`, and the parsed steps.

**Usage:** Example `~/.quantagent/workflows/my_morning_routine.yaml`:
```yaml
name: my_morning_routine
description: "My personal morning market review"
steps:
  - tool: get_market_summary
    parameters: {}
    output_key: market
  - tool: screen_oversold_reversal
    parameters: {rsi_threshold: 35}
    output_key: candidates
```
Then in Python: `load_custom_workflow("my_morning_routine")`, or via the
agent tool: run workflow `my_morning_routine` (no target needed unless a
step's parameters reference one).

---

## list_workflows

**Agent-facing tool name:** `list_workflows_tool` (via `_list_workflows_tool`
in `tools_registry.py`).

**Purpose:** Enumerates every workflow the user can currently run — the five
built-ins plus any custom YAML files found under `~/.quantagent/workflows/`.

**Why built this way:** Returns a flat list of plain dicts (not `Workflow`
objects) so it's trivially JSON-serializable for the agent tool layer, and
tolerates unreadable/malformed custom YAML files (catching `OSError` and
`yaml.YAMLError` per file) so one broken custom workflow file doesn't break
discovery of the others.

**Math:** No math — enumeration logic:
1. For each name in `BUILTIN_WORKFLOWS`, emit `{"name": name, "type":
   "builtin", "description": factory.__doc__ or ""}` (the description is the
   factory function's docstring, e.g. `"Daily market review capped by the
   conviction synthesis."`).
2. For each `*.yaml` file under `workflows_dir()` (sorted by filename), try
   to read its `description:` field (empty string on read/parse failure) and
   emit `{"name": <filename stem>, "type": "custom", "description": ...}`.
3. Return builtins followed by customs.

**Usage:**
```python
list_workflows()
# -> [{"name": "daily_market_check", "type": "builtin", "description": "..."},
#     ..., {"name": "my_morning_routine", "type": "custom", "description": "..."}]
```
Agent-facing call takes no parameters.

---

## get_workflow

**Agent-facing tool name:** Not exposed directly — called internally by
`run_workflow_tool` (`_run_workflow_tool`) to resolve the `name`/`target`
arguments it receives into an actual `Workflow` before calling
`run_workflow`.

**Purpose:** Single entry point that resolves a workflow by name, whether
built-in (optionally parameterized by `target`) or custom (loaded from
YAML), and validates that built-ins requiring a target actually received
one.

**Why built this way:** Centralizes the "built-in vs. custom" and
"target-required vs. not" branching in one place so `run_workflow_tool`
doesn't need to know which workflows need a target or how each built-in
factory's argument is shaped (symbol string vs. list of symbols) — it just
passes through whatever `target` string the agent supplied.

**Math:** No math — a small decision tree:
1. If `name` isn't in `BUILTIN_WORKFLOWS`, delegate entirely to
   `load_custom_workflow(name)`.
2. If `name` is in `_TARGET_REQUIRED` (`stock_research`,
   `portfolio_rebalance_review`) and `target` is empty, raise `ValueError`.
3. For `stock_research`, call the factory with `target.upper()`.
4. For `portfolio_rebalance_review`, split `target` on commas, strip each
   piece, and call the factory with that list.
5. Otherwise (parameterless built-ins), call the factory with no arguments.

**Usage:**
```python
get_workflow("daily_market_check")               # no target needed
get_workflow("stock_research", target="aapl")     # -> stock_research("AAPL")
get_workflow("portfolio_rebalance_review", target="aapl, msft")
get_workflow("my_morning_routine")                 # falls through to custom YAML
```

---

## workflow_requires_target

**Agent-facing tool name:** Not exposed as an agent tool / internal
infrastructure — used by the TUI (`quantagent/tui/commands.py`,
`_handle_workflow`) to decide whether the interactive workflow picker should
prefill an input box awaiting a target (e.g. `/workflow stock_research `)
rather than submitting immediately.

**Purpose:** Reports whether a named built-in workflow's factory requires a
`target` argument to be constructed.

**Why built this way:** A tiny, explicit membership check against a fixed
set (`_TARGET_REQUIRED = {"stock_research", "portfolio_rebalance_review"}`)
rather than introspecting factory signatures — keeps the "does this need a
target" question answerable without importing/calling the factory, which
matters for UI code that needs the answer before it has a target to pass.

**Math:** None — `return name in _TARGET_REQUIRED`.

**Usage:**
```python
workflow_requires_target("stock_research")            # True
workflow_requires_target("daily_market_check")         # False
workflow_requires_target("my_custom_yaml_workflow")    # False (not a builtin)
```
