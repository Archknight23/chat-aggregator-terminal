"""Settings modal — edit channels, toggles, OAuth config."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Grid, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static

from chat_tui import settings


class SettingsModal(ModalScreen):
    """Modal screen for editing chat aggregator settings."""

    DEFAULT_CSS = """
    SettingsModal {
        align: center middle;
    }
    #settings_dialog {
        grid-size: 2;
        grid-gutter: 1 2;
        padding: 1 2;
        width: 80;
        height: auto;
        border: thick $background 80%;
        background: $surface;
    }
    #settings_title {
        column-span: 2;
        text-align: center;
        text-style: bold;
    }
    """

    BINDINGS = [("escape", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        current = settings.load_settings()
        with Grid(id="settings_dialog"):
            yield Static(":: CHAT AGGREGATOR SETTINGS", id="settings_title")
            yield Label("Twitch channel")
            yield Input(value=current.get("twitchChannel", ""), id="twitchChannel")
            yield Label("YouTube live ID / @handle / URL")
            yield Input(value=current.get("youtubeLiveId", ""), id="youtubeLiveId")
            yield Label("Kick channel")
            yield Input(value=current.get("kickChannel", ""), id="kickChannel")
            yield Label("Twitch Client ID")
            yield Input(value=current.get("twitchClientId", ""), id="twitchClientId")
            yield Label("Twitch OAuth scopes")
            yield Input(value=current.get("twitchRequestedScopes", ""), id="twitchRequestedScopes")
            yield Label("Twitch system name")
            yield Input(value=current.get("twitchSystemName", ""), id="twitchSystemName")
            yield Label("Enable Twitch events")
            yield Checkbox(value=bool(current.get("twitchEventsEnabled")), id="twitchEventsEnabled")
            with Horizontal(id="settings_buttons"):
                yield Button("Save & Start", id="settings_save", variant="primary")
                yield Button("Cancel", id="settings_cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings_cancel":
            self.dismiss(None)
        elif event.button.id == "settings_save":
            self._save()

    def action_dismiss(self) -> None:
        self.dismiss(None)

    def _save(self) -> None:
        def _val(input_id: str) -> str:
            widget = self.query_one(f"#{input_id}", Input)
            return widget.value.strip()

        cfg = {
            "twitchChannel": _val("twitchChannel"),
            "youtubeLiveId": _val("youtubeLiveId"),
            "kickChannel": _val("kickChannel"),
            "twitchClientId": _val("twitchClientId"),
            "twitchRequestedScopes": _val("twitchRequestedScopes"),
            "twitchSystemName": _val("twitchSystemName"),
            "twitchEventsEnabled": self.query_one("#twitchEventsEnabled", Checkbox).value,
        }
        settings.save_settings(cfg)
        self.dismiss(cfg)
