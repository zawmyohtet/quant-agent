from __future__ import annotations

import asyncio
import logging
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Static

logger = logging.getLogger(__name__)


class ApprovalDialog(ModalScreen):
    """Modal for HITL approval of a tool call."""

    CSS = """
    ApprovalDialog {
        align: center middle;
    }
    #approval-dialog {
        width: 60;
        height: auto;
        border: thick $background 80%;
        padding: 1 2;
    }
    .title {
        text-align: center;
        text-style: bold;
    }
    .args {
        color: $text-muted;
    }
    """

    def __init__(
        self, tool_name: str, args: dict[str, Any], future: asyncio.Future[bool], **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.tool_name = tool_name
        self.args = args
        self.future = future

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-dialog"):
            yield Static("Tool Approval Required", classes="title")
            yield Static(f"Tool:   {self.tool_name}")
            args_text = "  ".join(f'{k}="{v}"' for k, v in self.args.items())
            yield Static(f"Args:   {args_text}", classes="args")
            with Horizontal(classes="buttons"):
                yield Button("Approve (A)", variant="success", id="approve")
                yield Button("Reject (R)", variant="error", id="reject")

    def on_mount(self) -> None:
        self.query_one("#approve", Button).focus()

    def on_key(self, event: Key) -> None:
        if event.key in ("a", "A"):
            self._approve()
        elif event.key in ("r", "R") or event.key == "escape":
            self._reject()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "approve":
            self._approve()
        else:
            self._reject()

    def _approve(self) -> None:
        if not self.future.done():
            self.future.set_result(True)
        self.dismiss()

    def _reject(self) -> None:
        if not self.future.done():
            self.future.set_result(False)
        self.dismiss()
