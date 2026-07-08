"""Composer input bar with platform selector."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Input, Static

from chat_tui.theme import C_DIM, C_FG, C_KICK, C_LOCAL, C_TWITCH, C_YOUTUBE


class Composer(Horizontal):
    """Bottom input bar with platform selector and send button."""

    DEFAULT_CSS = """
    Composer {
        height: 3;
        width: 1fr;
        background: $surface;
        border: solid $secondary;
    }
    Input {
        width: 1fr;
        background: $panel;
        color: #e8e8f0;
        border: tall $secondary 50%;
    }
    Input:focus {
        border: tall $secondary;
    }
    Button {
        width: 12;
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

    BINDINGS = [
        Binding("escape", "blur", "Blur", show=False),
    ]

    def action_blur(self) -> None:
        self.screen.focus_next()

    def compose(self):
        self._selector_label = Static("LOCAL", id="composer_platform")
        self._input = Input(placeholder="Type a message… (Tab to switch platform)", id="composer_input")
        yield self._selector_label
        yield self._input
        yield Button("SEND", id="composer_send", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "composer_send":
            self._submit()

    def on_input_submitted(self) -> None:
        self._submit()

    def action_switch_platform(self) -> None:
        """Cycle platform selector."""
        names = [p[0] for p in self.PLATFORMS]
        idx = names.index(self._platform)
        self._platform = names[(idx + 1) % len(names)]
        self._update_label()

    def _update_label(self) -> None:
        for key, label, color in self.PLATFORMS:
            if key == self._platform:
                self._selector_label.update(f"[{color}]{label}[/{color}]")
                return

    def _submit(self) -> None:
        text = self._input.value.strip()
        if not text:
            return
        self.post_message(self.SendMessage(self._platform, text))
        self._input.value = ""

    @property
    def platform(self) -> str:
        return self._platform

    def focus_input(self) -> None:
        self._input.focus()

    def set_platform(self, platform: str) -> None:
        if platform in {p[0] for p in self.PLATFORMS}:
            self._platform = platform
            self._update_label()
