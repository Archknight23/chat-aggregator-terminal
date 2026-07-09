"""Persistent one-line strip surfacing slash commands and key hints."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

C_HINT_SLASH = "#8a6bb0"
C_HINT_KEY = "#c77a3f"
C_HINT_THEME = "#00ffff"


class CommandHints(Static):
    """Always-visible reference for slash commands and key bindings."""

    DEFAULT_CSS = """
    CommandHints {
        height: 1;
        width: 1fr;
        background: $surface;
        padding: 0 1;
        content-align: left middle;
    }
    """

    def on_mount(self) -> None:
        self.update(self._build_text())

    def _build_text(self) -> Text:
        text = Text()
        text.append(":: ", style="#6b6b7a")
        text.append(
            "/settings  /clear  /raid <channel>  /platform <name>",
            style=C_HINT_SLASH,
        )
        text.append("   ")
        text.append(
            "[tab] platform  [t] theme  [s] settings  [c] clear",
            style=C_HINT_KEY,
        )
        text.append("   ")
        text.append("[q] quit", style=C_HINT_THEME)
        return text
