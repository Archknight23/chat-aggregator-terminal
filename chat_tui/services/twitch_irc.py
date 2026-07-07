"""Twitch IRC client — direct websocket connection (anonymous, read-only).

Replaces tmi.js. Connects to irc-ws.chat.twitch.tv:443, joins the channel
anonymously (no OAuth needed for read), and parses PRIVMSG + CLEARCHAT +
USERNOTICE messages.

Raid/host events come from the server's EventSub SSE, not IRC.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import websockets

logger = logging.getLogger(__name__)

TWITCH_IRC_URI = "wss://irc-ws.chat.twitch.tv:443"


class TwitchIRCClient:
    def __init__(self, channel: str, on_message: Any) -> None:
        self.channel = channel.lstrip("#").lower()
        self.on_message = on_message
        self._ws = None
        self._stop = asyncio.Event()
        self._reconnect_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._stop.clear()
        self._reconnect_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._ws:
            await self._ws.close()
        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    TWITCH_IRC_URI,
                    ping_interval=20,
                    ping_timeout=60,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    await ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
                    await ws.send(f"NICK justinfan{int(time.time()) % 10000}")
                    await ws.send(f"JOIN #{self.channel}")
                    backoff = 1.0
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        await self._handle_line(str(raw))
            except Exception as exc:
                logger.debug("Twitch IRC disconnected: %s", exc)
            self._ws = None
            if not self._stop.is_set():
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return

        # PING/PONG keepalive
        if line.startswith("PING"):
            if self._ws:
                await self._ws.send("PONG :" + line[5:] if line.startswith("PING ") else "PONG")
            return

        # Parse IRC message
        # Format: @tags :nick!user@host PRIVMSG #channel :message
        tags_str = ""
        if line.startswith("@"):
            tags_str, line = line[1:].split(" ", 1)

        # Parse tags
        tags: dict[str, str] = {}
        if tags_str:
            for pair in tags_str.split(";"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    tags[k] = v.replace("\\:", ";").replace("\\s", " ").replace("\\\\", "\\")

        parts = line.split(" ", 3)
        if len(parts) < 4:
            return

        source = parts[0]  # :nick!user@host
        cmd = parts[1]
        channel = parts[2]
        trailing = parts[3].lstrip(":")

        nick = source.lstrip(":").split("!")[0] if "!" in source else source.lstrip(":")

        if cmd == "PRIVMSG":
            display_name = tags.get("display-name") or nick
            sent_ts = tags.get("tmi-sent-ts")
            timestamp = int(sent_ts) if sent_ts and sent_ts.isdigit() else int(time.time() * 1000)

            await self.on_message({
                "username": display_name,
                "text": trailing,
                "platform": "twitch",
                "timestamp": timestamp,
                "id": tags.get("id"),
            })

        elif cmd == "CLEARCHAT":
            # Timeout or ban
            target_user = tags.get("target-user-id")
            if target_user:
                await self.on_message({
                    "username": "twitch",
                    "text": f"[timeout] {trailing}",
                    "platform": "system",
                    "timestamp": int(time.time() * 1000),
                })

        elif cmd == "USERNOTICE":
            msg_id = tags.get("msg-id", "")
            system_msg = tags.get("system-msg", trailing)
            if msg_id == "raid":
                display_name = tags.get("msg-param-displayName") or tags.get("msg-param-login") or "Someone"
                viewers = tags.get("msg-param-viewerCount", "0")
                await self.on_message({
                    "username": display_name,
                    "text": f"RAID — {display_name} ({viewers} viewers)",
                    "platform": "system",
                    "timestamp": int(time.time() * 1000),
                    "meta": {"eventType": "raid", "viewers": int(viewers) if viewers.isdigit() else 0},
                })
            elif system_msg:
                await self.on_message({
                    "username": "twitch",
                    "text": system_msg,
                    "platform": "system",
                    "timestamp": int(time.time() * 1000),
                })