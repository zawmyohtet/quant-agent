from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import ListItem, ListView, Static

logger = logging.getLogger(__name__)


@dataclass
class PickerItem:
    """One selectable row in a PickerScreen."""

    value: str
    label: str
    needs_target: bool = False
    target_hint: str = ""


class PickerScreen(ModalScreen):
    """Modal that lets the user pick one item from a list with the arrow keys.

    The screen is intentionally dumb: it renders the given items and, on
    selection, invokes ``on_select(item)`` and dismisses. The caller decides
    what selecting an item means (run it, prefill the input, etc.).
    """

    def __init__(
        self,
        title: str,
        items: list[PickerItem],
        on_select: Callable[[PickerItem], None],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._items = items
        self._on_select = on_select

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-dialog") as dialog:
            dialog.border_title = self._title
            yield ListView(id="picker-list")
            yield Static(Text("enter select  ·  esc cancel"), classes="modal-muted")

    def on_mount(self) -> None:
        list_view = self.query_one("#picker-list", ListView)
        for entry in self._items:
            item = ListItem(Static(Text.from_markup(entry.label)))
            item.picker_item = entry  # type: ignore[attr-defined]
            list_view.append(item)
        if list_view.children:
            list_view.index = 0

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        entry = getattr(event.item, "picker_item", None)
        self.dismiss()
        if entry is not None:
            self._on_select(entry)
