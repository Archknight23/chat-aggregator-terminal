"""Alert / event log widget for raids, rewards, status events."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget

from chat_tui.emoji_safe import demojize
from chat_tui.theme import C_DIM, C_FG, severity_color


class AlertRow(Widget, can_focus=False):
    """Single alert/event row."""

    DEFAULT_CSS = """
    AlertRow {
        height: auto;
        width: 1fr;
        margin: 0 0 1 0;
        padding: 0 1;
    }
    """

    def __init__(self, event: dict[str, Any], **kwargs) -> None:
        super().__init__(**kwargs)
        self.event = event

    def render(self) -> Text:
        event = self.event
        text = demojize(str(event.get("text") or event.get("eventType") or "event"))
        ts = event.get("timestamp")
        ts_str = ""
        if ts:
            try:
                if isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(ts / 1000.0)
                else:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                ts_str = dt.strftime("%H:%M:%S")
            except Exception:
                ts_str = str(ts)[:8]

        out = Text()
        if ts_str:
            out.append(f"[{ts_str}] ", style=C_DIM)
        out.append(text, style=severity_color(text))
        return out


class AlertLog(VerticalScroll):
    """Right-side alert/event rail."""

    events: reactive[list[dict[str, Any]]] = reactive(list)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._max_rows = 200

    def watch_events(self, events: list[dict[str, Any]]) -> None:
        self.remove_children()
        for event in events:
            self.mount(AlertRow(event))
        if events:
            self.scroll_end(animate=False)

    def add(self, event: dict[str, Any]) -> None:
        self.events = (self.events + [event])[-self._max_rows :]

    def clear(self) -> None:
        self.events = []
