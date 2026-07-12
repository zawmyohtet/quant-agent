from __future__ import annotations

import inspect
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from quantagent.tui.config import _DEFAULT_CONFIG_DIR
from quantagent.tui.widgets.chat_footer import ChatFooter
from quantagent.tui.widgets.message_view import MessageView
from quantagent.tui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from quantagent.tui.app import QuantAgentApp

logger = logging.getLogger(__name__)


@dataclass
class SlashCommand:
    """A slash command registered in the TUI."""

    name: str
    usage: str
    description: str
    handler: Callable[[list[str], QuantAgentApp], None | Awaitable[None]]
    aliases: list[str] = field(default_factory=list)
    arg_completer: Callable[[], list[str]] | None = None


def _handle_model(args: list[str], app: QuantAgentApp) -> None:
    if not args:
        _system(app, "Usage: /model <provider:model>")
        return
    model = args[0]
    app.state.config.model = model
    app.state.config.save()
    _system(app, f"Model set to {model}")
    _refresh_status(app)


def _handle_provider(args: list[str], app: QuantAgentApp) -> None:
    if not args:
        _system(app, "Usage: /provider <name>")
        return
    provider = args[0]
    app.state.config.provider = provider
    app.state.config.save()
    _system(app, f"Provider set to {provider}")
    _refresh_status(app)


def _handle_theme(args: list[str], app: QuantAgentApp) -> None:
    available = sorted(app.available_themes)
    if not args:
        lines = ["**Available themes:**\n"]
        for name in available:
            marker = " (current)" if name == app.theme else ""
            lines.append(f"  `{name}`{marker}")
        lines.append("\nUsage: /theme <name>")
        _system(app, "\n".join(lines))
        return
    name = args[0]
    if name not in app.available_themes:
        _system(
            app,
            f"Unknown theme: {name}. Valid themes: {', '.join(available)}",
        )
        return
    app.theme = name
    _system(app, f"Theme set to {name}")


def _theme_names() -> list[str]:
    from textual.theme import BUILTIN_THEMES

    return sorted(BUILTIN_THEMES)


def _handle_apikey(args: list[str], app: QuantAgentApp) -> None:
    if len(args) < 2:
        _system(app, "Usage: /apikey <provider> <key>")
        return
    provider, key = args[0], args[1]
    env_path = _DEFAULT_CONFIG_DIR / ".env"
    _DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()

    var_name = f"{provider.upper()}_API_KEY"
    new_line = f"{var_name}={key}"

    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{var_name}="):
            lines[i] = new_line
            updated = True
            break
    if not updated:
        lines.append(new_line)

    env_path.write_text("\n".join(lines) + "\n")
    os.chmod(env_path, 0o600)
    _system(app, f"API key for {provider} saved.")


def _handle_new(args: list[str], app: QuantAgentApp) -> None:
    app.state.new_thread()
    messages = app.query_one("#messages", MessageView)
    messages.clear()
    _system(app, "Started new thread.")
    _refresh_status(app)


def _handle_threads(args: list[str], app: QuantAgentApp) -> None:
    from quantagent.tui.widgets.thread_selector import ThreadSelectorScreen

    app.push_screen(ThreadSelectorScreen())


def _handle_clear(args: list[str], app: QuantAgentApp) -> None:
    messages = app.query_one("#messages", MessageView)
    messages.clear()
    _system(app, "Messages cleared.")


def _handle_export(args: list[str], app: QuantAgentApp) -> None:
    thread_id = app.state.thread_id
    default_path = Path.home() / f"quantagent-{thread_id}.md"
    path = Path(args[0]) if args else default_path
    messages = app.query_one("#messages", MessageView)
    md = messages.export_markdown()
    path.write_text(md)
    _system(app, f"Thread exported to {path}")


def _handle_stop(args: list[str], app: QuantAgentApp) -> None:
    if hasattr(app, "runner") and app.runner:
        app.runner.cancel()
    _system(app, "Agent turn cancelled.")


async def _handle_retry(args: list[str], app: QuantAgentApp) -> None:
    messages = app.query_one("#messages", MessageView)
    last_user = messages.last_user_message()
    if last_user:
        await app._submit_user_message(last_user)
    else:
        _system(app, "No previous user message to retry.")


def _handle_memory(args: list[str], app: QuantAgentApp) -> None:
    memory_path = _DEFAULT_CONFIG_DIR / "QUANTAGENT.md"
    if memory_path.exists():
        content = memory_path.read_text()
        _system(app, f"**QUANTAGENT.md**\n\n{content}")
    else:
        _system(app, "No QUANTAGENT.md found. Create one at ~/.quantagent/QUANTAGENT.md")


def _handle_approve(args: list[str], app: QuantAgentApp) -> None:
    app.state.pre_approve_next = True
    _system(app, "Next tool call will be auto-approved.")


async def _handle_analyze(args: list[str], app: QuantAgentApp) -> None:
    if not args:
        _system(app, "Usage: /analyze <SYMBOL>")
        return
    symbol = args[0].upper()
    await app._submit_user_message(f"Perform a full analysis of {symbol}")


async def _handle_backtest(args: list[str], app: QuantAgentApp) -> None:
    if len(args) < 2:
        _system(app, "Usage: /backtest <SYMBOL> <strategy>")
        return
    symbol, strategy = args[0].upper(), args[1]
    await app._submit_user_message(f"Run a backtest for {symbol} using {strategy} strategy")


async def _handle_screen(args: list[str], app: QuantAgentApp) -> None:
    if not args:
        _system(app, "Usage: /screen <criteria>")
        return
    criteria = " ".join(args)
    await app._submit_user_message(f"Screen stocks where {criteria}")


async def _handle_market(args: list[str], app: QuantAgentApp) -> None:
    await app._submit_user_message(
        "Give me a market overview: current regime, timing signals "
        "(distribution days, follow-through day), breadth, sector performance, "
        "and the recommended equity exposure."
    )


async def _handle_sector(args: list[str], app: QuantAgentApp) -> None:
    if args:
        sector = " ".join(args)
        await app._submit_user_message(
            f"Analyze the {sector} sector: performance across timeframes, "
            "relative strength vs SPY, top industries, and rotation context."
        )
        return
    await app._submit_user_message(
        "Rank all sectors by performance and relative strength, and detect "
        "the current sector rotation pattern."
    )


async def _handle_journal(args: list[str], app: QuantAgentApp) -> None:
    if args and args[0] == "add":
        if len(args) < 3:
            _system(app, "Usage: /journal add <SYMBOL> <thesis>")
            return
        symbol, thesis = args[1].upper(), " ".join(args[2:])
        await app._submit_user_message(
            f"Log a trade idea for {symbol} in the journal with this thesis: "
            f"{thesis}. Ask me for the entry plan, target, and stop if needed."
        )
        return
    await app._submit_user_message("Show my trade journal: open trades, recent history, and stats.")


async def _handle_riskgate(args: list[str], app: QuantAgentApp) -> None:
    await app._submit_user_message(
        "Check the risk circuit breaker and summarize my current trading discipline status."
    )


async def _handle_workflow(args: list[str], app: QuantAgentApp) -> None:
    if not args:
        _system(app, "Usage: /workflow <name> [target]")
        return
    name = args[0]
    target = " ".join(args[1:])
    detail = f" with target {target}" if target else ""
    await app._submit_user_message(
        f"Run the '{name}' workflow{detail} and walk me through the results."
    )


async def _handle_workflows(args: list[str], app: QuantAgentApp) -> None:
    await app._submit_user_message("List the available analysis workflows and what each one does.")


async def _handle_report(args: list[str], app: QuantAgentApp) -> None:
    if not args:
        _system(app, "Usage: /report <market|sector|stock|portfolio|screening> [target]")
        return
    report_type = args[0].lower()
    target = " ".join(args[1:])
    detail = f" for {target}" if target else ""
    await app._submit_user_message(
        f"Generate a {report_type} report{detail} and save it as markdown. "
        "Summarize the key findings."
    )


async def _handle_universe(args: list[str], app: QuantAgentApp) -> None:
    if not args:
        _system(app, "Usage: /universe <name>")
        return
    name = args[0].lower()
    await app._submit_user_message(
        f"Use the '{name}' universe for screening in this conversation. "
        "Confirm it exists and tell me its symbol count."
    )


async def _handle_universes(args: list[str], app: QuantAgentApp) -> None:
    await app._submit_user_message(
        "List all available screening universes with their symbol counts."
    )


async def _handle_heatmap(args: list[str], app: QuantAgentApp) -> None:
    metric = args[0] if args else "performance"
    await app._submit_user_message(
        f"Generate a market heatmap by sector using the {metric} metric "
        "and summarize what stands out."
    )


async def _handle_warm(args: list[str], app: QuantAgentApp) -> None:
    universe = args[0].lower() if args else "sp500"
    await app._submit_user_message(
        f"Warm the breadth cache for the '{universe}' universe using the "
        "warm_breadth_cache tool, then confirm how many symbols and rows "
        "were ingested. Note this can take several minutes."
    )


async def _handle_compare(args: list[str], app: QuantAgentApp) -> None:
    if len(args) < 2:
        _system(app, "Usage: /compare <SYM1> <SYM2> ...")
        return
    symbols = " ".join(s.upper() for s in args)
    await app._submit_user_message(f"Compare {symbols}")


def _handle_help(args: list[str], app: QuantAgentApp) -> None:
    if args:
        name = args[0].lstrip("/")
        cmd = find_command(name)
        if cmd:
            _system(app, f"**/{cmd.name}** — {cmd.description}\n\nUsage: {cmd.usage}")
        else:
            _system(app, f"Unknown command: /{name}")
        return

    lines = ["**Available commands:**\n"]
    for cmd in REGISTRY:
        lines.append(f"  `/{cmd.name}` — {cmd.description}")
    _system(app, "\n".join(lines))


def _system(app: QuantAgentApp, text: str) -> None:
    messages = app.query_one("#messages", MessageView)
    messages.add_system_message(text)


def _refresh_status(app: QuantAgentApp) -> None:
    status = app.query_one("#status-bar", StatusBar)
    status.refresh_state()
    footer = app.query_one("#chat-footer", ChatFooter)
    if hasattr(footer, "refresh_state"):
        footer.refresh_state()


REGISTRY: list[SlashCommand] = [
    SlashCommand("model", "/model <provider:model>", "Set LLM model.", _handle_model),
    SlashCommand("provider", "/provider <name>", "Set stock data provider.", _handle_provider),
    SlashCommand(
        "theme",
        "/theme [name]",
        "List or switch the UI theme.",
        _handle_theme,
        arg_completer=_theme_names,
    ),
    SlashCommand(
        "apikey", "/apikey <provider> <key>", "Save API key to ~/.quantagent/.env.", _handle_apikey
    ),
    SlashCommand("new", "/new", "Start fresh conversation thread.", _handle_new),
    SlashCommand("threads", "/threads", "Open thread selector modal.", _handle_threads),
    SlashCommand("clear", "/clear", "Clear visible messages.", _handle_clear),
    SlashCommand("export", "/export [path]", "Export current thread as Markdown.", _handle_export),
    SlashCommand("stop", "/stop", "Cancel currently running agent turn.", _handle_stop),
    SlashCommand("retry", "/retry", "Re-submit last user message.", _handle_retry),
    SlashCommand("memory", "/memory", "Print QUANTAGENT.md content.", _handle_memory),
    SlashCommand("approve", "/approve", "Pre-approve next tool call.", _handle_approve),
    SlashCommand(
        "analyze", "/analyze <SYMBOL>", "Perform full analysis of a stock.", _handle_analyze
    ),
    SlashCommand(
        "backtest",
        "/backtest <SYMBOL> <strategy>",
        "Run a backtest for a symbol using a strategy.",
        _handle_backtest,
    ),
    SlashCommand(
        "screen", "/screen <criteria>", "Screen stocks matching criteria.", _handle_screen
    ),
    SlashCommand(
        "market", "/market", "Market overview: regime, breadth, timing, exposure.", _handle_market
    ),
    SlashCommand(
        "sector",
        "/sector [name]",
        "Sector analysis (all sectors, or one by name).",
        _handle_sector,
    ),
    SlashCommand(
        "heatmap",
        "/heatmap [metric]",
        "Market heatmap (performance/volume/volatility/rsi).",
        _handle_heatmap,
    ),
    SlashCommand(
        "warm",
        "/warm [universe]",
        "Warm breadth cache (sp500/nasdaq100/sector_etfs).",
        _handle_warm,
    ),
    SlashCommand(
        "report",
        "/report <type> [target]",
        "Generate a report (market/sector/stock/portfolio/screening).",
        _handle_report,
    ),
    SlashCommand(
        "workflow", "/workflow <name> [target]", "Run a predefined workflow.", _handle_workflow
    ),
    SlashCommand("workflows", "/workflows", "List available workflows.", _handle_workflows),
    SlashCommand(
        "journal",
        "/journal [add <SYMBOL> <thesis>]",
        "View trade journal, or log a trade idea.",
        _handle_journal,
    ),
    SlashCommand(
        "riskgate", "/riskgate", "Check circuit breaker & discipline status.", _handle_riskgate
    ),
    SlashCommand(
        "universe", "/universe <name>", "Switch active screening universe.", _handle_universe
    ),
    SlashCommand(
        "universes", "/universes", "List available screening universes.", _handle_universes
    ),
    SlashCommand(
        "compare",
        "/compare <SYM1> <SYM2> ...",
        "Compare multiple stocks.",
        _handle_compare,
    ),
    SlashCommand("help", "/help [command]", "Show available commands.", _handle_help),
]

_COMMAND_MAP: dict[str, SlashCommand] = {}
for _cmd in REGISTRY:
    _COMMAND_MAP[_cmd.name] = _cmd
    for _alias in _cmd.aliases:
        _COMMAND_MAP[_alias] = _cmd


def find_command(name: str) -> SlashCommand | None:
    """Look up a slash command by name or alias."""
    return _COMMAND_MAP.get(name)


async def dispatch(raw: str, app: QuantAgentApp) -> None:
    """Parse and execute a slash command."""
    parts = raw.lstrip("/").split()
    if not parts:
        return
    name, *args = parts
    cmd = find_command(name)
    if cmd:
        result = cmd.handler(args, app)
        if inspect.isawaitable(result):
            await result
    else:
        _system(app, f"Unknown command: /{name}. Type /help for available commands.")
