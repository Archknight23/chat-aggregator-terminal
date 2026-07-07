"""Per-platform viewer count bar."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Label

from chat_tui.theme import C_DIM, C_FG, C_KICK, C_LOCAL, C_TWITCH, C_YOUTUBE


class ViewerBar(Horizontal):
    """Horizontal bar showing viewer counts per platform."""

    DEFAULT_CSS = """
    ViewerBar {
        height: 3;
        width: 1fr;
        background: #15131c;
        color: #e8e8f0;
        border-bottom: solid #a855f7;
        padding: 0 1;
    }
    ViewerBar Label {
        height: 1;
        width: 1fr;
        content-align: left middle;
    }
    """

    counts: reactive[dict[str, Any]] = reactive(dict)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._label = Label("")

    def compose(self) -> ComposeResult:
        yield self._label

    def on_mount(self) -> None:
        self._refresh_label()

    def watch_counts(self, counts: dict[str, Any]) -> None:
        self._refresh_label()

    def _refresh_label(self) -> None:
        counts = self.counts
        total = 0
        segments: list[tuple[str, str]] = []

        for platform, color in [
            ("twitch", C_TWITCH),
            ("youtube", C_YOUTUBE),
            ("kick", C_KICK),
            ("local", C_LOCAL),
        ]:
            value = counts.get(platform)
            label = platform.upper()
            if value is None:
                segments.append((f"{label}: —", C_DIM))
            else:
                try:
                    n = int(value)
                    total += n
                    segments.append((f"{label}: {n:,}", color))
                except (TypeError, ValueError):
                    segments.append((f"{label}: —", C_DIM))

        text = Text()
        for i, (seg, color) in enumerate(segments):
            if i:
                text.append("  |  ", style=C_DIM)
            text.append(seg, style=color)
        text.append(f"  :: TOTAL: {total:,}", style=f"bold {C_FG}")
        self._label.update(text)

    def update_count(self, platform: str, value: int | None) -> None:
        new = dict(self.counts)
        if value is None:
            new.pop(platform, None)
        else:
            new[platform] = value
        self.counts = new

    def clear(self) -> None:
        self.counts = {}
