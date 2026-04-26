from __future__ import annotations

import typer

from quantagent.tui.app import QuantAgentApp
from quantagent.tui.config import QuantAgentConfig, load_dotenv_file

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
    QuantAgentApp(config=config).run()


if __name__ == "__main__":
    app()
