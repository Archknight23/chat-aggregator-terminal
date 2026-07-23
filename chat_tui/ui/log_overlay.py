"""Toggleable log overlay — tabbed status/alert history."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TabbedContent, TabPane

from chat_tui.emoji_safe import demojize
from chat_tui.theme import C_DIM, C_FG, severity_color


def _format_row(item: dict[str, Any]) -> Text:
    text = demojize(str(item.get("text") or item.get("eventType") or "event"))
    ts = item.get("timestamp")
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
    sev = item.get("severity")
    out.append(text, style=severity_color(text) if sev == "error" else C_FG)
    return out


class LogOverlay(ModalScreen):
    """Tabbed history of status messages and stream alerts."""

    DEFAULT_CSS = """
    LogOverlay {
        align: center middle;
    }
    #log_dialog {
        width: 90%;
        max-width: 100;
        height: 80%;
        border: thick $background 80%;
        background: $surface;
    }
    #log_tabs {
        height: 1fr;
    }
    #log_tabs TabPane {
        padding: 1 2;
    }
    #log_status_body, #log_alerts_body {
        height: 1fr;
    }
    .log_row {
        height: auto;
        margin: 0 0 1 0;
    }
    #log_close {
        margin: 1 2;
    }
    """

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self, status_items: list[dict[str, Any]], alert_items: list[dict[str, Any]], **kwargs) -> None:
        super().__init__(**kwargs)
        self._status_items = status_items
        self._alert_items = alert_items

    def compose(self) -> ComposeResult:
        with Vertical(id="log_dialog"):
            with TabbedContent(id="log_tabs"):
                with TabPane("Status", id="log_tab_status"):
                    with VerticalScroll(id="log_status_body"):
                        if self._status_items:
                            for item in self._status_items:
                                yield Static(_format_row(item), classes="log_row")
                        else:
                            yield Static("No status history yet.", classes="log_row")
                with TabPane("Alerts", id="log_tab_alerts"):
                    with VerticalScroll(id="log_alerts_body"):
                        if self._alert_items:
                            for item in self._alert_items:
                                yield Static(_format_row(item), classes="log_row")
                        else:
                            yield Static("No alerts yet.", classes="log_row")
            yield Button("Close", id="log_close")

    def on_mount(self) -> None:
        self.query_one("#log_status_body", VerticalScroll).scroll_end(animate=False)
        self.query_one("#log_alerts_body", VerticalScroll).scroll_end(animate=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "log_close":
            self.dismiss(None)

    def action_dismiss(self) -> None:
        self.dismiss(None)
