"""Composer input bar with platform selector."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Input

from chat_tui.theme import C_DIM, C_FG, C_KICK, C_LOCAL, C_TWITCH, C_YOUTUBE, Theme


class Composer(Horizontal):
    """Bottom input bar with platform selector and send button."""

    DEFAULT_CSS = """
    Composer {
        height: 5;
        width: 1fr;
        background: $panel;
        border: solid $secondary;
        align-vertical: middle;
    }
    #composer_platform {
        width: 10;
        min-width: 10;
        height: 3;
        content-align: center middle;
        background: $panel;
        border: none;
    }
    #composer_input {
        width: 1fr;
        background: $panel;
        color: #e8e8f0;
        border: tall $secondary 50%;
    }
    #composer_input:focus {
        border: tall $secondary;
    }
    #composer_send {
        width: 10;
        min-width: 10;
        background: $secondary;
        color: #0a0a0f;
        text-style: bold;
    }
    """

    class SendMessage(Message):
        """Posted when user sends a message."""

        def __init__(self, platform: str, text: str) -> None:
            super().__init__()
            self.platform = platform
            self.text = text

    PLATFORMS = [
        ("local", "LOCAL", C_LOCAL),
        ("twitch", "TWITCH", C_TWITCH),
        ("youtube", "YT", C_YOUTUBE),
        ("kick", "KICK", C_KICK),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._platform = "local"
        self._theme: Theme | None = None

    BINDINGS = [
        Binding("escape", "blur", "Blur", show=False),
    ]

    def action_blur(self) -> None:
        self.screen.focus_next()

    def compose(self):
        self._selector_label = Button("LOCAL", id="composer_platform")
        self._selector_label.tooltip = "Change destination"
        self._input = Input(placeholder="Message LOCAL", id="composer_input", max_length=500)
        yield self._selector_label
        yield self._input
        yield Button("SEND", id="composer_send", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "composer_send":
            self._submit()
        elif event.button.id == "composer_platform":
            self.action_switch_platform()
            self.focus_input()

    def on_input_submitted(self) -> None:
        self._submit()

    def action_switch_platform(self) -> None:
        """Cycle platform selector."""
        names = [p[0] for p in self.PLATFORMS]
        idx = names.index(self._platform)
        self._platform = names[(idx + 1) % len(names)]
        self._update_label()

    def _update_label(self) -> None:
        theme = self._theme
        for key, label, default_color in self.PLATFORMS:
            if key == self._platform:
                color = theme.platform_local if theme and key == "local" else \
                        theme.platform_twitch if theme and key == "twitch" else \
                        theme.platform_youtube if theme and key == "youtube" else \
                        theme.platform_kick if theme and key == "kick" else default_color
                self._selector_label.label = label
                self._selector_label.styles.color = color
                self._input.placeholder = f"Message {label}"
                return

    def _submit(self) -> None:
        text = self._input.value.strip()
        if not text:
            return
        self.post_message(self.SendMessage(self._platform, text))
        self._input.value = ""
        self.focus_input()

    @property
    def platform(self) -> str:
        return self._platform

    def focus_input(self) -> None:
        self._input.focus()

    def set_platform(self, platform: str) -> None:
        if platform in {p[0] for p in self.PLATFORMS}:
            self._platform = platform
            self._update_label()

    @property
    def theme(self) -> Theme | None:
        return self._theme

    @theme.setter
    def theme(self, value: Theme | None) -> None:
        self._theme = value
        self._update_label()
