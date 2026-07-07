"""Settings persistence — JSON instead of localStorage."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_TWITCH_SYSTEM_NAME = "CHAOSFOUNDRY // SYS"
DEFAULT_TWITCH_SCOPES = "channel:read:redemptions channel:manage:raids user:write:chat"

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "chat-aggregator-tui"
CONFIG_FILE = CONFIG_DIR / "settings.json"


def default_settings() -> dict[str, Any]:
    return {
        "twitchChannel": "",
        "youtubeLiveId": "",
        "kickChannel": "",
        "twitchEventsEnabled": False,
        "twitchClientId": "",
        "twitchSystemName": DEFAULT_TWITCH_SYSTEM_NAME,
        "twitchRequestedScopes": DEFAULT_TWITCH_SCOPES,
    }


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
    return {
        "twitchChannel": str(settings.get("twitchChannel") or "").strip(),
        "youtubeLiveId": str(settings.get("youtubeLiveId") or "").strip(),
        "kickChannel": str(settings.get("kickChannel") or "").strip(),
        "twitchEventsEnabled": bool(settings.get("twitchEventsEnabled")),
        "twitchClientId": str(settings.get("twitchClientId") or "").strip(),
        "twitchSystemName": str(settings.get("twitchSystemName") or DEFAULT_TWITCH_SYSTEM_NAME).strip(),
        "twitchRequestedScopes": str(settings.get("twitchRequestedScopes") or DEFAULT_TWITCH_SCOPES).strip(),
    }