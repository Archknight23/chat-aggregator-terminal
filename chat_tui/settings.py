"""Settings persistence — JSON instead of localStorage."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

DEFAULT_TWITCH_SYSTEM_NAME = "CHAOSFOUNDRY // SYS"
DEFAULT_TWITCH_SCOPES = "channel:read:redemptions channel:manage:raids user:write:chat"
# Opt-in only — do not phone home to production without an explicit setting.
# Operators set chatFeedUrl in Settings (e.g. https://chaosfoundry.digital).
DEFAULT_CHAT_FEED_URL = ""


def _get_config_dir() -> Path:
    """Return platform-appropriate config directory."""
    if sys.platform == "win32":
        # Windows: %APPDATA%\chat-aggregator-tui
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "chat-aggregator-tui"
        return Path.home() / ".config" / "chat-aggregator-tui"
    elif sys.platform == "darwin":
        # macOS: ~/Library/Application Support/chat-aggregator-tui
        return Path.home() / "Library" / "Application Support" / "chat-aggregator-tui"
    else:
        # Linux and others: XDG_CONFIG_HOME or ~/.config
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            return Path(xdg) / "chat-aggregator-tui"
        return Path.home() / ".config" / "chat-aggregator-tui"


CONFIG_DIR = _get_config_dir()
CONFIG_FILE = CONFIG_DIR / "settings.json"


def default_settings() -> dict[str, Any]:
    return {
        "twitchChannel": "",
        "youtubeLiveId": "",
        "kickChannel": "",
        "twitchEventsEnabled": False,
        "twitchClientId": "",
        "twitchClientSecret": "",
        "twitchSystemName": DEFAULT_TWITCH_SYSTEM_NAME,
        "twitchRequestedScopes": DEFAULT_TWITCH_SCOPES,
        "chatFeedUrl": DEFAULT_CHAT_FEED_URL,
        "localIngest": True,
    }


def sanitize_twitch_channel(value: str) -> str:
    """Normalize a Twitch channel login (lowercase, no #).

    Does not invent a different login from mangled paste garbage — that is
    too lossy. Operators should fix bad values in Settings; we only strip
    the # prefix and lowercase so IRC joins the intended room.
    """
    return str(value or "").strip().lstrip("#").lower()


def sanitize_youtube_target(value: str) -> str:
    """Normalize YouTube live targets; collapse mangled @handle paste garbage."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    # Full URLs / video IDs pass through once cleaned of whitespace
    if "youtube.com" in raw or "youtu.be" in raw or re.fullmatch(r"[\w-]{11}", raw):
        return raw
    # Handle: keep a single @name
    handles = re.findall(r"@([A-Za-z0-9._-]{3,30})", raw)
    if handles:
        # last distinct-ish handle wins (user retyped over selection)
        return "@" + handles[-1]
    if raw.startswith("@"):
        return "@" + re.sub(r"[^A-Za-z0-9._-]", "", raw[1:])[:30]
    return raw


def sanitize_chat_feed_url(value: str) -> str:
    """Reduce the remote feed setting to a bare origin (scheme://host[:port]).

    Operators tend to paste the endpoint URL they just tested in a browser
    or curl (e.g. .../api/chat/stream) rather than the bare domain. remote_feed.py
    appends its own /api/chat/* suffixes, so a leftover path here doubles up
    into a permanently 404ing URL — a fast, silent reconnect loop rather than
    a real network failure. Also repairs a missing slash after the scheme
    (e.g. "https:/host" from a fumbled paste/edit).
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"^(https?):/+", r"\1://", raw, flags=re.IGNORECASE)
    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}"


def load_settings() -> dict[str, Any]:
    try:
        raw = CONFIG_FILE.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return default_settings()
        merged = default_settings()
        merged.update(parsed)
        return merged
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default_settings()


def save_settings(settings: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(settings, indent=2, sort_keys=True), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def normalize(settings: dict[str, Any]) -> dict[str, Any]:
    # Missing key → empty (no implicit production URL). Explicit empty string stays empty.
    if "chatFeedUrl" in settings:
        feed = str(settings.get("chatFeedUrl") or "").strip()
    else:
        feed = DEFAULT_CHAT_FEED_URL
    local = settings.get("localIngest")
    if local is None:
        local = True
    return {
        "twitchChannel": sanitize_twitch_channel(str(settings.get("twitchChannel") or "")),
        "youtubeLiveId": sanitize_youtube_target(str(settings.get("youtubeLiveId") or "")),
        "kickChannel": str(settings.get("kickChannel") or "").strip().lstrip("#"),
        "twitchEventsEnabled": bool(settings.get("twitchEventsEnabled")),
        "twitchClientId": str(settings.get("twitchClientId") or "").strip(),
        "twitchClientSecret": str(settings.get("twitchClientSecret") or "").strip(),
        "twitchSystemName": str(settings.get("twitchSystemName") or DEFAULT_TWITCH_SYSTEM_NAME).strip(),
        "twitchRequestedScopes": str(settings.get("twitchRequestedScopes") or DEFAULT_TWITCH_SCOPES).strip(),
        "chatFeedUrl": sanitize_chat_feed_url(feed),
        "localIngest": bool(local),
    }