from __future__ import annotations

import contextlib
import logging

import typer

from quantagent.tui.app import QuantAgentApp
from quantagent.tui.config import QuantAgentConfig, load_dotenv_file
from quantagent.utils.logging import init_file_logging, install_excepthook

app = typer.Typer()


@app.command()
def run(
    model: str = typer.Option(None, "--model", "-m", help="Override model, e.g. openai:gpt-4o"),
    provider: str = typer.Option(None, "--provider", "-p", help="Override data provider"),
    thread: str = typer.Option(None, "--thread", "-t", help="Resume a thread by ID"),
) -> None:
    """Launch QuantAgent interactive terminal UI."""
    load_dotenv_file()
    config = QuantAgentConfig.load()
    if model:
        config.model = model
    if provider:
        config.provider = provider
    if thread:
        config.thread_id = thread
    init_file_logging()
    install_excepthook()
    logging.getLogger(__name__).info("File logging initialized at ~/.quantagent/logs/errors.log")

    with contextlib.suppress(KeyboardInterrupt):
        QuantAgentApp(config=config).run()


if __name__ == "__main__":
    app()
