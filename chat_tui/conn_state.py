"""Connection state helpers for viewer bar indicators."""

from __future__ import annotations

from enum import Enum


class ConnState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"

    def icon(self) -> str:
        return {
            ConnState.DISCONNECTED: "○",
            ConnState.CONNECTING: "◐",
            ConnState.CONNECTED: "●",
            ConnState.ERROR: "✕",
        }[self]

    def color(self) -> str:
        return {
            ConnState.DISCONNECTED: "#6b6b7a",
            ConnState.CONNECTING: "#ffcc00",
            ConnState.CONNECTED: "#00ff88",
            ConnState.ERROR: "#ff4444",
        }[self]
