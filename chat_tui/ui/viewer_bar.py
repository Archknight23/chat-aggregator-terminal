"""Per-platform viewer count bar with connection indicators."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Label

from chat_tui.conn_state import ConnState
from chat_tui.theme import C_DIM, C_FG, C_KICK, C_LOCAL, C_TWITCH, C_YOUTUBE, Theme


class ViewerBar(Horizontal):
    """Horizontal bar showing connection status and viewer counts per platform."""

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
    connections: reactive[dict[str, ConnState]] = reactive(dict)
    theme: reactive[Theme | None] = reactive(None)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._label = Label("")
        self._pulse_on = True
        self._compact = False

    def compose(self) -> ComposeResult:
        yield self._label

    def on_mount(self) -> None:
        self._refresh_label()
        self.set_interval(0.5, self._pulse_tick)

    def _pulse_tick(self) -> None:
        if not any(state == ConnState.CONNECTING for state in self.connections.values()):
            return
        self._pulse_on = not self._pulse_on
        self._refresh_label()

    def watch_counts(self, counts: dict[str, Any]) -> None:
        self._refresh_label()

    def watch_connections(self, connections: dict[str, ConnState]) -> None:
        self._refresh_label()

    def watch_theme(self, theme: Theme | None) -> None:
        """Refresh label when theme changes."""
        self._refresh_label()

    def _refresh_label(self) -> None:
        total = 0
        text = Text()

        theme = self.theme
        platform_colors = {
            "twitch": theme.platform_twitch if theme else C_TWITCH,
            "youtube": theme.platform_youtube if theme else C_YOUTUBE,
            "kick": theme.platform_kick if theme else C_KICK,
            "local": theme.platform_local if theme else C_LOCAL,
        }

        for i, (platform, color) in enumerate(platform_colors.items()):
            if i:
                text.append(" | " if self._compact else "  |  ", style=C_DIM)

            value = self.counts.get(platform)
            conn = self.connections.get(platform, ConnState.DISCONNECTED)
            label = platform.upper()
            if self._compact:
                label = {"twitch": "TW", "youtube": "YT", "kick": "K", "local": "L"}[platform]
            icon = conn.icon()
            if conn == ConnState.CONNECTING:
                icon_style = f"{'bold' if self._pulse_on else 'dim'} {conn.color()}"
            else:
                icon_style = f"bold {conn.color()}"

            if value is None:
                count_text = "—"
            else:
                try:
                    n = int(value)
                    total += n
                    count_text = f"{n:,}"
                except (TypeError, ValueError):
                    count_text = "—"

            text.append(f"{icon} ", style=icon_style)
            text.append(f"{label}: {count_text}", style=color)

        # Use theme accent for total if available
        total_color = theme.accent_primary if theme else C_FG
        text.append(
            f" | Σ {total:,}" if self._compact else f"  :: TOTAL: {total:,}",
            style=f"bold {total_color}",
        )
        self._label.update(text)

    def set_compact(self, compact: bool) -> None:
        if compact != self._compact:
            self._compact = compact
            self._refresh_label()

    def update_count(self, platform: str, value: int | None) -> None:
        new = dict(self.counts)
        if value is None:
            new.pop(platform, None)
        else:
            new[platform] = value
        self.counts = new

    def set_connection(self, platform: str, state: ConnState) -> None:
        new = dict(self.connections)
        new[platform] = state
        self.connections = new

    def clear(self) -> None:
        self.counts = {}
        self.connections = {}
