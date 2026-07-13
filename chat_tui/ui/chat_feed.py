"""Unified chat feed widget — scrollable message list per platform."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget

from chat_tui.emoji_safe import demojize
from chat_tui.theme import C_BG, C_DIM, C_FG, C_SYSTEM, Theme, platform_color


class ChatMessage(Widget, can_focus=False):
    """Single chat message row."""

    DEFAULT_CSS = """
    ChatMessage {
        height: auto;
        width: 1fr;
        background: $surface-darken-1;
        margin: 0 0 1 0;
        padding: 0 1;
        border-left: thick #6b6b7a;
    }
    ChatMessage.platform-twitch {
        border-left: thick #a970ff;
    }
    ChatMessage.platform-youtube {
        border-left: thick #ff4444;
    }
    ChatMessage.platform-kick {
        border-left: thick #53fc18;
    }
    ChatMessage.platform-local {
        border-left: thick #ff6b1a;
    }
    """

    def __init__(self, message: dict[str, Any], theme: Theme | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message
        self.theme = theme or None

    def on_mount(self) -> None:
        platform = (self.message.get("platform") or "system").lower()
        if platform in ("twitch", "youtube", "kick", "local"):
            self.add_class(f"platform-{platform}")
        self.styles.opacity = 0.0
        self.styles.animate("opacity", value=1.0, duration=0.2)
        # Apply theme border color if available
        if self.theme:
            color = platform_color(platform, self.theme)
            self.styles.border_left = ("thick", color)

    def render(self) -> Text:
        msg = self.message
        platform = (msg.get("platform") or "system").lower()
        username = demojize(str(msg.get("username") or "—"))
        text = demojize(str(msg.get("text") or ""))
        ts = msg.get("timestamp")

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
        out.append(f"{username}: ", style=f"bold {platform_color(platform, self.theme)}")
        out.append(text, style=C_FG)
        return out


class ChatFeed(VerticalScroll):
    """Scrollable feed of chat messages."""

    messages: reactive[list[dict[str, Any]]] = reactive(list)
    theme: reactive[Theme | None] = reactive(None)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._max_rows = 500

    def watch_messages(self, messages: list[dict[str, Any]]) -> None:
        """Synchronize bulk replacements such as clear or theme refresh."""
        if not messages:
            self.remove_children()

    def watch_theme(self, theme: Theme | None) -> None:
        """Refresh all messages when theme changes."""
        self.remove_children()
        for msg in self.messages:
            self.mount(ChatMessage(msg, theme=self.theme))
        if self.messages:
            self.scroll_end(animate=False)

    def add(self, message: dict[str, Any]) -> None:
        messages = self.messages + [message]
        overflow = max(0, len(messages) - self._max_rows)
        self.messages = messages[overflow:]
        for child in list(self.children)[:overflow]:
            child.remove()
        self.mount(ChatMessage(message, theme=self.theme))
        self.call_after_refresh(self._trim_children)
        self.call_after_refresh(self.scroll_end, animate=False)

    def _trim_children(self) -> None:
        overflow = max(0, len(self.children) - self._max_rows)
        for child in list(self.children)[:overflow]:
            child.remove()

    def clear(self) -> None:
        self.messages = []
