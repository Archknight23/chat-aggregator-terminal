"""One-line status / alert / error ticker."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from chat_tui.emoji_safe import demojize
from chat_tui.theme import C_DIM, C_FG, severity_color


class StatusTicker(Static):
    """Scrolling-ish ticker of recent status, alerts, and errors."""

    DEFAULT_CSS = """
    StatusTicker {
        height: 1;
        width: 1fr;
        background: #0a0a0f;
        color: #6b6b7a;
        padding: 0 1;
        content-align: left middle;
    }
    """

    items: reactive[list[dict[str, Any]]] = reactive(list)
    max_items: int = 200

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)

    def watch_items(self, items: list[dict[str, Any]]) -> None:
        self.update(self._build_text(items))

    def add(self, text: str, severity: str = "info", timestamp: float | None = None) -> None:
        ts = timestamp or datetime.now().timestamp() * 1000
        new_item = {
            "text": text,
            "severity": severity,
            "timestamp": ts,
        }
        self.items = (self.items + [new_item])[-self.max_items :]

    def clear(self) -> None:
        self.items = []

    def _build_text(self, items: list[dict[str, Any]]) -> Text:
        if not items:
            return Text(":: awaiting events — press s for settings", style=C_DIM)

        item = items[-1]
        ts = item.get("timestamp")
        ts_str = ""
        if ts:
            try:
                dt = datetime.fromtimestamp(ts / 1000.0)
                ts_str = dt.strftime("%H:%M:%S")
            except Exception:
                pass
        sev = item.get("severity", "info")
        body = demojize(str(item.get("text", "")))

        text = Text(":: ", style=C_DIM)
        if ts_str:
            text.append(f"[{ts_str}] ", style=C_DIM)
        text.append(body, style=severity_color(body) if sev == "error" else C_FG)
        return text
