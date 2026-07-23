"""Settings modal — edit channels, toggles, OAuth config."""

from __future__ import annotations

import asyncio
import time

from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static

from chat_tui import settings
from chat_tui.services.twitch_oauth import TwitchDeviceAuth, TwitchOAuthError, activation_url, open_verification_url


class SettingsModal(ModalScreen):
    """Modal screen for editing chat aggregator settings."""

    DEFAULT_CSS = """
    SettingsModal {
        align: center middle;
    }
    #settings_scroll {
        width: 90%;
        max-width: 90;
        height: 90%;
        border: thick $background 80%;
        background: $surface;
    }
    #settings_dialog {
        grid-size: 2;
        grid-gutter: 1 2;
        padding: 1 2;
        height: auto;
    }
    #settings_title {
        column-span: 2;
        text-align: center;
        text-style: bold;
    }
    SettingsModal Input {
        background: #15131c;
        color: #e8e8f0;
        border: tall #6b6b7a;
    }
    SettingsModal Input:focus {
        background: #0a0a0f;
        color: #ffffff;
        border: tall $secondary;
    }
    SettingsModal Checkbox:focus {
        border: tall $secondary;
    }
    #twitch_auth_row {
        column-span: 2;
        height: auto;
    }
    #twitch_auth_status {
        height: 3;
        padding: 0 1;
        background: $panel;
        border: solid $primary 40%;
        color: #e8e8f0;
    }
    #twitch_auth_buttons {
        column-span: 2;
        height: 3;
    }
    #twitch_auth_buttons Button {
        margin-right: 1;
    }
    #twitch_secret_field {
        width: 1fr;
        height: 3;
    }
    #twitch_secret_field Input {
        width: 1fr;
    }
    #twitch_secret_toggle {
        width: 9;
        margin-left: 1;
    }
    """

    BINDINGS = [("escape", "dismiss", "Close")]

    def __init__(self) -> None:
        super().__init__()
        self._auth_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        # The running app's settings are authoritative. Re-reading disk here
        # can show a blank form if its config lookup differs from the client
        # that is already connected with populated channels.
        current = getattr(self.app, "_settings", None)
        if not isinstance(current, dict):
            current = settings.load_settings()
        with VerticalScroll(id="settings_scroll"):
            with Grid(id="settings_dialog"):
                yield Static(":: CHAT AGGREGATOR SETTINGS", id="settings_title")
                yield Label("Twitch channel")
                yield Input(value=current.get("twitchChannel", ""), id="twitchChannel", password=False)
                yield Label("YouTube live ID / @handle / URL")
                yield Input(value=current.get("youtubeLiveId", ""), id="youtubeLiveId")
                yield Label("Kick channel")
                yield Input(value=current.get("kickChannel", ""), id="kickChannel")
                yield Label("Remote chat feed URL (VPS, blank = off)")
                yield Input(value=current.get("chatFeedUrl", ""), id="chatFeedUrl")
                yield Label("Local ingest (Twitch IRC / Kick poll / YT)")
                yield Checkbox(value=bool(current.get("localIngest", True)), id="localIngest")
                yield Label("Twitch Client ID")
                yield Input(value=current.get("twitchClientId", ""), id="twitchClientId")
                yield Label("Twitch Client Secret (confidential apps only)")
                with Horizontal(id="twitch_secret_field"):
                    yield Input(value=current.get("twitchClientSecret", ""), id="twitchClientSecret", password=True)
                    yield Button("Show", id="twitch_secret_toggle")
                yield Label("Twitch OAuth scopes")
                yield Input(value=current.get("twitchRequestedScopes", ""), id="twitchRequestedScopes")
                yield Label("Twitch system name")
                yield Input(value=current.get("twitchSystemName", ""), id="twitchSystemName")
                yield Label("Enable Twitch events")
                yield Checkbox(value=bool(current.get("twitchEventsEnabled")), id="twitchEventsEnabled")
                with Vertical(id="twitch_auth_row"):
                    yield Static("Twitch status: unknown — start the TUI to query the server.", id="twitch_auth_status")
                    with Horizontal(id="twitch_auth_buttons"):
                        yield Button("Authenticate (Device)", id="twitch_auth_device", variant="primary")
                        yield Button("Status", id="twitch_auth_status_btn")
                        yield Button("Logout", id="twitch_auth_logout", variant="warning")
                with Horizontal(id="settings_buttons"):
                    yield Button("Save & Connect", id="settings_save", variant="primary")
                    yield Button("Cancel", id="settings_cancel")

    def on_mount(self) -> None:
        # Pull a fresh status snapshot when the modal opens so the user sees
        # the real server state, not the stale settings file.
        self.run_worker(self._refresh_status(), exclusive=False)
        self.call_after_refresh(self._focus_twitch_channel_at_end)

    def _focus_twitch_channel_at_end(self) -> None:
        """Show the saved channel plainly instead of highlighting it as selected text."""
        channel = self.query_one("#twitchChannel", Input)
        channel.focus()
        channel.cursor_position = len(channel.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "settings_cancel":
            self.dismiss(None)
        elif bid == "settings_save":
            self._save()
        elif bid == "twitch_auth_device":
            self._start_device_auth()
        elif bid == "twitch_auth_status_btn":
            self.run_worker(self._refresh_status(), exclusive=False)
        elif bid == "twitch_auth_logout":
            self.run_worker(self._do_logout(), exclusive=False)
        elif bid == "twitch_secret_toggle":
            self._toggle_secret_visibility()

    def action_dismiss(self) -> None:
        if self._auth_task and not self._auth_task.done():
            self._auth_task.cancel()
        self.dismiss(None)

    def _set_status_text(self, text: str) -> None:
        try:
            widget = self.query_one("#twitch_auth_status", Static)
            widget.update(text)
        except Exception:
            pass

    def _input(self, input_id: str) -> str:
        return self.query_one(f"#{input_id}", Input).value.strip()

    def _toggle_secret_visibility(self) -> None:
        field = self.query_one("#twitchClientSecret", Input)
        field.password = not field.password
        self.query_one("#twitch_secret_toggle", Button).label = "Hide" if not field.password else "Show"

    def _save(self) -> None:
        cfg = {
            "twitchChannel": self._input("twitchChannel"),
            "youtubeLiveId": self._input("youtubeLiveId"),
            "kickChannel": self._input("kickChannel"),
            "chatFeedUrl": self._input("chatFeedUrl"),
            "localIngest": self.query_one("#localIngest", Checkbox).value,
            "twitchClientId": self._input("twitchClientId"),
            "twitchClientSecret": self._input("twitchClientSecret"),
            "twitchRequestedScopes": self._input("twitchRequestedScopes"),
            "twitchSystemName": self._input("twitchSystemName"),
            "twitchEventsEnabled": self.query_one("#twitchEventsEnabled", Checkbox).value,
        }
        normalized = settings.normalize(cfg)
        settings.save_settings(normalized)
        self.dismiss(normalized)

    async def _refresh_status(self) -> None:
        server = getattr(self.app, "server", None)
        if not server or not getattr(server, "_http", None):
            self._set_status_text("Twitch status: server not reachable.")
            return
        status = await server.twitch_status()
        if not status:
            self._set_status_text("Twitch status: unable to query server.")
            return
        if not status.get("hasAuth"):
            self._set_status_text("Twitch status: not authenticated. Click Authenticate (Device).")
            return
        login = status.get("login") or "?"
        expires_at = status.get("expiresAt")
        try:
            expired = expires_at is not None and float(expires_at) <= time.time() * 1000
        except (TypeError, ValueError):
            expired = False
        if expired:
            self._set_status_text(
                f"Twitch status: {login} — token expired. Click Authenticate (Device) to re-authorize."
            )
            return
        connected = "connected" if status.get("connected") else "auth ok — EventSub not yet connected"
        scopes = ", ".join(status.get("scopes") or []) or "(none)"
        self._set_status_text(f"Twitch status: {login} — {connected}\n  scopes: {scopes}")

    async def _do_logout(self) -> None:
        server = getattr(self.app, "server", None)
        if not server or not getattr(server, "_http", None):
            self._set_status_text("Logout failed: server not reachable.")
            return
        result = await server.twitch_logout()
        if result.get("ok"):
            self._set_status_text("Twitch status: logged out.")
        else:
            self._set_status_text(f"Logout failed: {result.get('error') or 'unknown'}")

    def _start_device_auth(self) -> None:
        if self._auth_task and not self._auth_task.done():
            self._set_status_text("Auth already in progress — wait for it to finish or cancel.")
            return
        self._auth_task = asyncio.create_task(self._run_device_auth())

    async def _run_device_auth(self) -> None:
        client_id = self._input("twitchClientId")
        client_secret = self._input("twitchClientSecret") or None
        scopes_raw = self._input("twitchRequestedScopes")
        scopes = [s for s in scopes_raw.split() if s] if scopes_raw else []

        if not client_id:
            self._set_status_text("Auth failed: set Twitch Client ID first.")
            return

        server = getattr(self.app, "server", None)
        if not server or not getattr(server, "_http", None):
            self._set_status_text("Auth failed: local server not reachable. Is `npm run server` running?")
            return

        auth = TwitchDeviceAuth(server)
        try:
            self._set_status_text("Requesting device code from Twitch…")
            code = await auth.start({"clientId": client_id, "clientSecret": client_secret, "scopes": scopes})
        except TwitchOAuthError as exc:
            self._set_status_text(f"Auth failed to start: {exc}")
            return
        except Exception as exc:
            self._set_status_text(f"Auth failed to start: {exc}")
            return

        verify_url = activation_url(code)
        user_code = code.get("userCode", "")
        opened = open_verification_url(verify_url)
        opener_note = "" if opened else " (couldn't open a browser automatically — open it manually)"
        self._set_status_text(
            f"Open in your browser{opener_note}:\n  {verify_url}\n"
            f"Enter code: {user_code}\nAuthorize it, then return here. Twitch may send you to Connections."
        )

        async def on_pending(state: str, elapsed: float, total: float) -> None:
            self._set_status_text(
                f"Open in your browser: {verify_url}\n"
                f"Enter code: {user_code}  •  waiting {int(elapsed)}s / {int(total)}s ({state})\n"
                "After Authorize, the Twitch Connections page is normal."
            )

        try:
            result = await auth.poll(
                code,
                {"clientId": client_id, "clientSecret": client_secret, "scopes": scopes},
                on_pending=on_pending,
            )
        except TwitchOAuthError as exc:
            self._set_status_text(f"Auth failed: {exc}")
            return
        except asyncio.CancelledError:
            self._set_status_text("Auth cancelled.")
            raise
        except Exception as exc:
            self._set_status_text(f"Auth failed: {exc}")
            return

        st = result.get("status") or {}
        login = st.get("login") or "?"
        connected = "connected" if st.get("connected") else "auth ok — EventSub connecting"
        self._set_status_text(f"Twitch authenticated as {login} — {connected}.")
