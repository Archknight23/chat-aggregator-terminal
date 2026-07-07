"""Main Textual app for the chat aggregator TUI."""

from __future__ import annotations

import asyncio
import logging
import sys
import webbrowser
from pathlib import Path
from typing import Any

import httpx
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static

from chat_tui import settings
from chat_tui.bus import MSG_ALERT, MSG_CHAT, MSG_SEND_STATUS, MSG_STATUS, MSG_VIEWER_COUNT, MessageBus
from chat_tui.conn_state import ConnState
from chat_tui.services.kick_client import KickClient
from chat_tui.services.server_client import ServerClient
from chat_tui.services.twitch_irc import TwitchIRCClient
from chat_tui.ui.alert_log import AlertLog
from chat_tui.ui.chat_feed import ChatFeed
from chat_tui.ui.composer import Composer
from chat_tui.ui.settings_modal import SettingsModal
from chat_tui.ui.status_ticker import StatusTicker
from chat_tui.ui.viewer_bar import ViewerBar

logger = logging.getLogger(__name__)

DEFAULT_SERVER_URL = "http://localhost:4174"
VIEWER_POLL_SECONDS = 10


class ChatAggregatorApp(App):
    """Terminal-native chat aggregator."""

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
    #chat_pane {
        width: 1fr;
        height: 1fr;
    }
    #chat_feed {
        border: solid $primary;
    }
    #ticker {
        height: 1;
        background: $surface;
        color: #6b6b7a;
        padding: 0 1;
        content-align: left middle;
    }
    #composer {
        height: 3;
        background: $panel;
        border-top: solid $primary;
    }
    #status_bar {
        display: none;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("s", "settings", "Settings", show=True),
        Binding("c", "clear", "Clear", show=True),
        Binding("tab", "switch_platform", "Platform", show=True),
        Binding("ctrl+l", "clear", "Clear", show=False),
    ]

    status_text: reactive[str] = reactive(":: CHAT AGGREGATOR TUI")

    def __init__(self, server_url: str = DEFAULT_SERVER_URL, **kwargs) -> None:
        super().__init__(**kwargs)
        self.server_url = server_url
        self.title = "CHAT AGGREGATOR"
        self.bus = MessageBus()
        self.server = ServerClient(server_url)
        self.twitch_irc: TwitchIRCClient | None = None
        self.kick: KickClient | None = None
        self._tasks: list[asyncio.Task] = []
        self._settings = settings.load_settings()
        self._youtube_live_id: str | None = None
        self._running = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="main"):
            yield ViewerBar(id="viewer_bar")
            yield ChatFeed(id="chat_feed")
            yield StatusTicker(id="ticker")
            yield Composer(id="composer")
            yield Static(self.status_text, id="status_bar")
        yield Footer()

    async def on_mount(self) -> None:
        await self.server.start()
        self._running = True
        self._tasks.append(asyncio.create_task(self._bus_pump()))
        self._tasks.append(asyncio.create_task(self._viewer_poll_loop()))
        self._tasks.append(asyncio.create_task(self._twitch_sse_loop()))
        self._apply_settings(self._settings)
        self.query_one("#composer", Composer).focus_input()
        self._post_ticker("awaiting events — press s for settings", severity="dim")

    async def on_unmount(self) -> None:
        self._running = False
        await self._stop_clients()
        await self.server.stop()
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
        self._post_status("chat cleared")

    def action_switch_platform(self) -> None:
        self.query_one("#composer", Composer).action_switch_platform()

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
                "timestamp": int(asyncio.get_event_loop().time() * 1000),
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
        channel = ""
        if platform == "twitch":
            channel = self._settings.get("twitchChannel", "")
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
        self.query_one("#chat_feed", ChatFeed).add(message)

    def _post_alert(self, event: dict[str, Any]) -> None:
        text = str(event.get("text") or event.get("eventType") or "event")
        severity = "error" if "error" in str(event.get("eventType", "")).lower() else "info"
        self._post_ticker(text, severity=severity)

    def _post_ticker(self, text: str, severity: str = "info") -> None:
        self.query_one("#ticker", StatusTicker).add(text, severity=severity)

    def _set_status(self, payload: dict[str, Any]) -> None:
        text = payload.get("text", "")
        if text:
            self.status_text = text
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
        asyncio.create_task(self._apply_settings_async(cfg))

    async def _apply_settings_async(self, cfg: dict[str, Any]) -> None:
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
                self._youtube_live_id = resolved or youtube_target
                self._set_connection("youtube", ConnState.CONNECTED if resolved else ConnState.ERROR)
                self._post_status(f"YouTube live ID: {self._youtube_live_id}")
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
                            "timestamp": data.get("timestamp") or int(asyncio.get_event_loop().time() * 1000),
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
                # YouTube viewer count not wired server-side in this build
                await asyncio.sleep(VIEWER_POLL_SECONDS)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.exception("viewer poll error: %s", exc)
            self._post_ticker(f"viewer poll loop crashed: {exc}", severity="error")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler("/tmp/chat-aggregator-tui.log", mode="a")],
    )
    app = ChatAggregatorApp()
    app.run()


if __name__ == "__main__":
    main()
