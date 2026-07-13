"""Main Textual app for the chat aggregator TUI."""

from __future__ import annotations

import asyncio
from collections import deque
import logging
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any

import httpx
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.widgets import Footer, Header

from chat_tui import settings
from chat_tui.bus import MSG_ALERT, MSG_CHAT, MSG_SEND_STATUS, MSG_STATUS, MSG_VIEWER_COUNT, MessageBus
from chat_tui.conn_state import ConnState
from chat_tui.services.kick_client import KickClient
from chat_tui.services.node_backend import BackendStartupError, NodeBackendSupervisor
from chat_tui.services.server_client import ServerClient
from chat_tui.services.twitch_irc import TwitchIRCClient
from chat_tui.theme import THEME_ORDER, Theme, cycle_theme, get_theme
from chat_tui.ui.alert_log import AlertLog
from chat_tui.ui.chat_feed import ChatFeed
from chat_tui.ui.command_hints import CommandHints
from chat_tui.ui.composer import Composer
from chat_tui.ui.settings_modal import SettingsModal
from chat_tui.ui.status_ticker import StatusTicker
from chat_tui.ui.viewer_bar import ViewerBar

logger = logging.getLogger(__name__)

DEFAULT_SERVER_URL = "http://localhost:4174"
VIEWER_POLL_SECONDS = 10


class ChatAggregatorApp(App):
    """Terminal-native chat aggregator."""

    ENABLE_COMMAND_PALETTE = False

    CSS = """
    $primary: #a855f7;
    $secondary: #ff6b1a;
    $surface: #0a0a0f;
    $background: #0a0a0f;
    $panel: #15131c;

    Screen {
        align: center top;
        background: $surface;
    }
    Header {
        background: $panel;
        color: $secondary;
        text-style: bold;
        border-bottom: solid $primary;
    }
    #main {
        width: 1fr;
        height: 1fr;
    }
    #viewer_bar {
        height: 3;
        background: $panel;
        color: #e8e8f0;
        border-bottom: solid $primary;
    }
    #content_row {
        width: 1fr;
        height: 1fr;
    }
    #chat_feed {
        width: 1fr;
        height: 1fr;
        border: thick $primary;
        scrollbar-gutter: stable;
        padding: 0 0;
    }
    #chat_feed:focus {
        border: double $secondary;
        background: $panel;
        padding: 0 1;
    }
    #alert_log {
        width: 34;
        height: 1fr;
        border: thick #ffd23f;
        scrollbar-gutter: stable;
        padding: 0 0;
    }
    #alert_log:focus {
        border: double #ff6b1a;
        background: $panel;
        padding: 0 1;
    }
    #ticker {
        height: 1;
        background: $surface;
        color: #6b6b7a;
        padding: 0 1;
        content-align: left middle;
    }
    #hints {
        height: 1;
        background: $surface;
        padding: 0 1;
        content-align: left middle;
    }
    #composer {
        height: 5;
        background: $panel;
        border: thick $secondary;
        padding: 0 0;
    }
    #composer:focus {
        border: double $secondary;
        background: $surface;
        text-style: bold;
        padding: 0 1;
    }
    Footer {
        background: $panel;
        color: $primary;
        border-top: solid $primary;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True, tooltip="Exit the application"),
        Binding("s", "settings", "Settings", show=True, priority=True, tooltip="Open settings modal"),
        Binding("f2", "settings", "Settings", show=False, priority=True),
        Binding("c", "clear", "Clear", show=True, priority=True, tooltip="Clear chat, alerts, and ticker"),
        Binding("tab", "switch_platform", "Platform", show=True, priority=True, tooltip="Cycle through platforms (Local/Twitch/YouTube/Kick)"),
        Binding("t", "theme", "Theme", show=True, priority=True, tooltip="Cycle through color themes"),
        Binding("ctrl+l", "clear", "Clear", show=False, priority=True),
    ]

    def __init__(self, server_url: str = DEFAULT_SERVER_URL, **kwargs) -> None:
        super().__init__(**kwargs)
        self.server_url = server_url
        self.title = "CHAT AGGREGATOR"
        self.bus = MessageBus()
        self.server = ServerClient(server_url)
        self.backend = NodeBackendSupervisor(server_url)
        self.twitch_irc: TwitchIRCClient | None = None
        self.kick: KickClient | None = None
        self._tasks: list[asyncio.Task] = []
        self._settings_task: asyncio.Task | None = None
        self._youtube_task: asyncio.Task | None = None
        self._settings = settings.load_settings()
        self._youtube_live_id: str | None = None
        self._seen_message_ids: set[str] = set()
        self._message_id_order: deque[str] = deque(maxlen=2_000)
        self._running = False
        self._theme_name = "frutiger_aero"
        self._theme = get_theme(self._theme_name)

    def compose(self) -> ComposeResult:
        chat_feed = ChatFeed(id="chat_feed")
        chat_feed.border_title = "CHAT FEED"
        alert_log = AlertLog(id="alert_log")
        alert_log.border_title = "ALERTS"
        composer = Composer(id="composer")
        composer.border_title = "COMPOSER"

        yield Header(show_clock=True)
        with Vertical(id="main"):
            yield ViewerBar(id="viewer_bar")
            with Horizontal(id="content_row"):
                yield chat_feed
                yield alert_log
            yield StatusTicker(id="ticker")
            yield CommandHints(id="hints")
            yield composer
        yield Footer()

    async def on_mount(self) -> None:
        await self.server.start()
        try:
            backend_state = await self.backend.ensure_running(self.server)
        except BackendStartupError as exc:
            backend_state = f"error: {exc}"
        self._running = True
        self._tasks.append(asyncio.create_task(self._bus_pump()))
        self._tasks.append(asyncio.create_task(self._viewer_poll_loop()))
        self._tasks.append(asyncio.create_task(self._twitch_sse_loop()))
        self._apply_settings(self._settings)
        self.query_one("#composer", Composer).focus_input()
        if backend_state == "started":
            self._post_ticker("local backend started", severity="info")
        elif backend_state == "existing":
            self._post_ticker("local backend already running", severity="dim")
        else:
            self._post_ticker(f"backend unavailable: {backend_state}", severity="error")
        self._post_ticker("awaiting events — press s for settings", severity="dim")

    async def on_unmount(self) -> None:
        self._running = False
        await self._cancel_task(self._settings_task)
        self._settings_task = None
        await self._stop_youtube()
        await self._stop_clients()
        await self.server.stop()
        await self.backend.stop()
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def action_settings(self) -> None:
        self.push_screen(SettingsModal(), self._on_settings_closed)

    def action_clear(self) -> None:
        self.query_one("#chat_feed", ChatFeed).clear()
        self.query_one("#ticker", StatusTicker).clear()
        self.query_one("#alert_log", AlertLog).clear()
        self._post_status("chat cleared")

    def action_switch_platform(self) -> None:
        self.query_one("#composer", Composer).action_switch_platform()

    def action_theme(self) -> None:
        """Cycle to the next theme."""
        self._theme_name, self._theme = cycle_theme(self._theme_name)
        self._apply_theme()
        self._post_ticker(f"theme → {self._theme.name}", severity="info")

    def on_resize(self, event: Resize) -> None:
        """Keep core chat and composer usable on narrow terminals."""
        try:
            compact = event.size.width < 100
            self.query_one("#alert_log", AlertLog).display = not compact
            self.query_one("#hints", CommandHints).set_compact(compact)
            self.query_one("#viewer_bar", ViewerBar).set_compact(event.size.width < 80)
        except Exception:
            # Resize may arrive before the widget tree has mounted.
            pass

    def _apply_theme(self) -> None:
        """Apply the current theme by updating widget styles."""
        t = self._theme
        
        # Update widget themes
        self.query_one("#chat_feed", ChatFeed).theme = self._theme
        self.query_one("#viewer_bar", ViewerBar).theme = self._theme
        self.query_one("#composer", Composer).theme = self._theme
        
        # Update focused widget styles dynamically
        focused = self.focused
        if focused:
            focused.styles.border = ("double", t.accent_primary)
        
        # Update header title to show theme
        self.title = f"CHAT AGGREGATOR — {t.name.upper()}"
        self.sub_title = t.description
        
        # Refresh the ticker to show theme change
        self.query_one("#ticker", StatusTicker).add(f"theme → {t.name}", severity="info")

    def _on_settings_closed(self, result: dict[str, Any] | None) -> None:
        if result is not None:
            self._settings = settings.normalize(result)
            self._apply_settings(self._settings)

    def on_composer_send_message(self, event: Composer.SendMessage) -> None:
        if event.text.startswith("/"):
            self._handle_slash(event.text)
            return
        if event.platform == "local":
            self._post_chat({
                "username": "me",
                "text": event.text,
                "platform": "local",
                "timestamp": int(time.time() * 1000),
            })
            return
        self._post_status(f"sending → {event.platform}…")
        asyncio.create_task(self._send_outbound(event.platform, event.text))

    def _handle_slash(self, text: str) -> None:
        parts = text[1:].split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        if cmd == "settings":
            self.action_settings()
        elif cmd == "clear":
            self.action_clear()
        elif cmd == "raid":
            if not arg:
                self._post_alert({"text": "Usage: /raid <channel>", "eventType": "error"})
                return
            asyncio.create_task(self._send_raid(arg))
        elif cmd == "platform":
            self.query_one("#composer", Composer).set_platform(arg.lower())
        else:
            self._post_alert({"text": f"Unknown command: /{cmd}", "eventType": "error"})

    async def _send_outbound(self, platform: str, text: str) -> None:
        channel_keys = {
            "twitch": "twitchChannel",
            "youtube": "youtubeLiveId",
            "kick": "kickChannel",
        }
        channel = self._settings.get(channel_keys.get(platform, ""), "")
        result = await self.server.send_message(platform, text, channel)
        ok = bool(result.get("ok"))
        self.bus.put_nowait(
            MSG_SEND_STATUS,
            {
                "ok": ok,
                "platform": platform,
                "error": result.get("error"),
                "text": text,
            },
        )

    async def _send_raid(self, target: str) -> None:
        result = await self.server.initiate_raid(target)
        self._post_alert({
            "text": f"Raid to {target}: {result.get('status') or result.get('error') or 'unknown'}",
            "eventType": "raid",
            "timestamp": int(asyncio.get_event_loop().time() * 1000),
        })

    async def _bus_pump(self) -> None:
        while self._running:
            try:
                msg = await self.bus.get()
                if msg.kind == MSG_CHAT:
                    self._post_chat(msg.payload)
                elif msg.kind == MSG_ALERT:
                    self._post_alert(msg.payload)
                elif msg.kind == MSG_STATUS:
                    self._set_status(msg.payload)
                elif msg.kind == MSG_VIEWER_COUNT:
                    self._update_viewer(msg.payload)
                elif msg.kind == MSG_SEND_STATUS:
                    self._on_send_status(msg.payload)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.exception("bus pump error: %s", exc)

    def _post_chat(self, message: dict[str, Any]) -> None:
        if self._is_duplicate_message(message):
            return
        self.query_one("#chat_feed", ChatFeed).add(message)

    def _is_duplicate_message(self, message: dict[str, Any]) -> bool:
        message_id = message.get("id")
        if message_id:
            dedupe_key = f"{message.get('platform', 'unknown')}:{message_id}"
            if dedupe_key in self._seen_message_ids:
                return True
            if len(self._message_id_order) == self._message_id_order.maxlen:
                self._seen_message_ids.discard(self._message_id_order[0])
            self._message_id_order.append(dedupe_key)
            self._seen_message_ids.add(dedupe_key)
        return False

    def _post_alert(self, event: dict[str, Any]) -> None:
        text = str(event.get("text") or event.get("eventType") or "event")
        severity = "error" if "error" in str(event.get("eventType", "")).lower() else "info"
        self._post_ticker(text, severity=severity)
        self.query_one("#alert_log", AlertLog).add(event)

    def _post_ticker(self, text: str, severity: str = "info") -> None:
        self.query_one("#ticker", StatusTicker).add(text, severity=severity)

    def _set_status(self, payload: dict[str, Any]) -> None:
        text = payload.get("text", "")
        if text:
            self._post_ticker(text, severity="info")

    def _update_viewer(self, payload: dict[str, Any]) -> None:
        platform = payload.get("platform")
        count = payload.get("count")
        if platform:
            self.query_one("#viewer_bar", ViewerBar).update_count(platform, count)

    def _set_connection(self, platform: str, state: ConnState) -> None:
        self.query_one("#viewer_bar", ViewerBar).set_connection(platform, state)

    def _on_send_status(self, payload: dict[str, Any]) -> None:
        ok = payload.get("ok")
        platform = str(payload.get("platform") or "?")
        error = payload.get("error")
        text = payload.get("text", "")
        if ok:
            self._post_ticker(f"SENT [{platform.upper()}] {text}", severity="info")
        else:
            self._post_ticker(f"FAILED [{platform.upper()}] {error or 'unknown'}", severity="error")

    def _post_status(self, text: str) -> None:
        self.bus.put_nowait(MSG_STATUS, {"text": text})

    def _apply_settings(self, cfg: dict[str, Any]) -> None:
        if self._settings_task and not self._settings_task.done():
            self._settings_task.cancel()
        self._settings_task = asyncio.create_task(self._apply_settings_async(cfg))

    async def _apply_settings_async(self, cfg: dict[str, Any]) -> None:
        await self._stop_youtube()
        await self._stop_clients()

        twitch_channel = cfg.get("twitchChannel", "")
        youtube_target = cfg.get("youtubeLiveId", "")
        kick_channel = cfg.get("kickChannel", "")

        # mark configured platforms as connecting
        for platform, channel in [
            ("twitch", twitch_channel),
            ("youtube", youtube_target),
            ("kick", kick_channel),
        ]:
            self._set_connection(platform, ConnState.CONNECTING if channel else ConnState.DISCONNECTED)

        if twitch_channel:
            try:
                self.twitch_irc = TwitchIRCClient(
                    twitch_channel,
                    lambda m: self.bus.put_nowait(MSG_CHAT, m),
                )
                await self.twitch_irc.start()
                self._set_connection("twitch", ConnState.CONNECTED)
                self._post_status(f"Twitch IRC joined: #{twitch_channel}")
            except Exception as exc:
                self._set_connection("twitch", ConnState.ERROR)
                self._post_ticker(f"Twitch connect failed: {exc}", severity="error")

        if kick_channel:
            try:
                self.kick = KickClient(
                    kick_channel,
                    lambda m: self.bus.put_nowait(MSG_CHAT, m),
                )
                await self.kick.start()
                self._set_connection("kick", ConnState.CONNECTED)
                self._post_status(f"Kick polling: {kick_channel}")
            except Exception as exc:
                self._set_connection("kick", ConnState.ERROR)
                self._post_ticker(f"Kick connect failed: {exc}", severity="error")

        if youtube_target:
            try:
                resolved = await self.server.resolve_youtube_id(youtube_target)
                if not resolved:
                    self._set_connection("youtube", ConnState.ERROR)
                    self._post_ticker("YouTube stream is not live or could not be resolved", severity="error")
                else:
                    self._youtube_live_id = resolved
                    self._set_connection("youtube", ConnState.CONNECTED)
                    self._post_status(f"YouTube live ID: {self._youtube_live_id}")
                    self._youtube_task = asyncio.create_task(self._youtube_sse_loop(resolved))
            except Exception as exc:
                self._set_connection("youtube", ConnState.ERROR)
                self._post_ticker(f"YouTube resolve failed: {exc}", severity="error")

    async def _stop_clients(self) -> None:
        if self.twitch_irc:
            await self.twitch_irc.stop()
            self.twitch_irc = None
        if self.kick:
            await self.kick.stop()
            self.kick = None

    async def _stop_youtube(self) -> None:
        task = self._youtube_task
        self._youtube_task = None
        self._youtube_live_id = None
        await self._cancel_task(task)

    @staticmethod
    async def _cancel_task(task: asyncio.Task | None) -> None:
        if not task or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _twitch_sse_loop(self) -> None:
        """Consume Twitch EventSub SSE from server."""
        try:
            async for data in self.server.sse_stream("/api/twitch/sse"):
                if not self._running:
                    return
                if data.get("_disconnected"):
                    continue
                dtype = data.get("type")
                if dtype == "status":
                    self.bus.put_nowait(
                        MSG_STATUS,
                        {"text": f"Twitch events: {data.get('status')}"},
                    )
                elif dtype == "event":
                    event_type = data.get("eventType", "event")
                    event = data.get("event", {})
                    text = self._format_twitch_event(event_type, event)
                    self.bus.put_nowait(
                        MSG_ALERT,
                        {
                            "text": text,
                            "eventType": event_type,
                            "timestamp": data.get("timestamp") or int(time.time() * 1000),
                        },
                    )
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.exception("twitch sse loop error: %s", exc)

    def _format_twitch_event(self, event_type: str, event: dict[str, Any]) -> str:
        if event_type == "channel.raid":
            from_name = event.get("from_broadcaster_user_name") or event.get("from_broadcaster_user_login", "?")
            viewers = event.get("viewers", "?")
            return f"RAID — {from_name} ({viewers} viewers)"
        if event_type == "channel.channel_points_custom_reward_redemption.add":
            user = event.get("user_name") or event.get("user_login", "?")
            reward = event.get("reward", {}).get("title", "reward")
            return f"REWARD — {user} redeemed {reward}"
        return f"EVENT — {event_type}"

    async def _youtube_sse_loop(self, live_id: str) -> None:
        """Consume YouTube live chat SSE from server."""
        try:
            async for data in self.server.sse_stream(f"/api/youtube/sse?liveId={live_id}"):
                if not self._running:
                    return
                if data.get("_disconnected"):
                    continue
                # Server broadcasts chat payload directly: {id, username, text, timestamp}
                username = data.get("username", "—")
                text = data.get("text", "")
                if text and username:
                    self.bus.put_nowait(
                        MSG_CHAT,
                        {
                            "username": username,
                            "text": text,
                            "platform": "youtube",
                            "timestamp": data.get("timestamp") or int(time.time() * 1000),
                            "id": data.get("id"),
                        },
                    )
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.exception("youtube sse loop error: %s", exc)

    async def _viewer_poll_loop(self) -> None:
        """Poll viewer counts every 10 seconds."""
        try:
            await asyncio.sleep(2.0)
            while self._running:
                cfg = self._settings
                for platform, channel in [
                    ("twitch", cfg.get("twitchChannel", "")),
                    ("kick", cfg.get("kickChannel", "")),
                ]:
                    if channel:
                        try:
                            count = await self.server.fetch_viewers(platform, channel)
                            self.bus.put_nowait(MSG_VIEWER_COUNT, {"platform": platform, "count": count})
                        except Exception as exc:
                            self._post_ticker(f"viewer poll {platform} failed: {exc}", severity="error")
                            self._set_connection(platform, ConnState.ERROR)
                # YouTube viewer count polling
                if self._youtube_live_id:
                    try:
                        count = await self.server.fetch_viewers("youtube", self._youtube_live_id)
                        self.bus.put_nowait(MSG_VIEWER_COUNT, {"platform": "youtube", "count": count})
                    except Exception as exc:
                        self._post_ticker(f"viewer poll youtube failed: {exc}", severity="error")
                        self._set_connection("youtube", ConnState.ERROR)
                await asyncio.sleep(VIEWER_POLL_SECONDS)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.exception("viewer poll error: %s", exc)
            self._post_ticker(f"viewer poll loop crashed: {exc}", severity="error")


def main() -> None:
    import tempfile
    log_dir = Path(tempfile.gettempdir())
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "chat-aggregator-tui.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, mode="a")],
    )
    app = ChatAggregatorApp()
    app.run()


if __name__ == "__main__":
    main()
