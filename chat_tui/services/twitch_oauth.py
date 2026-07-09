"""Twitch device-code OAuth flow — terminal-native auth for the TUI.

Twitch's Device Authorization Grant (RFC 8628) is the flow Twitch documents
for "clients with limited input capabilities" — exactly the TUI case. It avoids
the loopback-redirect dance that a browser-based PKCE flow would require, and
works headless too (the user opens the verification URL on any device).

We delegate the actual /oauth2/device and /oauth2/token calls to the local
chat-aggregator server (`/api/twitch/device/start`, `/api/twitch/device/poll`)
so the server can persist the resulting token into the same `.twitch-auth.json`
its `TwitchEventSub` already watches — that means token refresh, EventSub
boot, and the `/api/twitch/sse` status feed all keep working unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import webbrowser

logger = logging.getLogger(__name__)


class TwitchOAuthError(Exception):
    """Raised when the device flow fails in a way the user can act on."""


def _response_json(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _oauth_error_code(payload: dict[str, Any], status_code: int) -> str:
    raw = (
        payload.get("error")
        or payload.get("message")
        or payload.get("errorDescription")
        or payload.get("error_description")
        or ""
    )
    normalized = str(raw).strip().lower().replace(" ", "_")
    return normalized or f"http_{status_code}"


def activation_url(code: dict[str, Any]) -> str:
    raw = str(code.get("verificationUri") or "https://www.twitch.tv/activate")
    user_code = str(code.get("userCode") or "").strip()
    if not user_code:
        return raw

    parsed = urlparse(raw)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "device-code" in query:
        return raw

    query.setdefault("public", "true")
    query["device-code"] = user_code
    return urlunparse(parsed._replace(query=urlencode(query)))


class TwitchDeviceAuth:
    """Runs one Twitch device-code auth round-trip against the local server.

    Lifecycle:
        auth = TwitchDeviceAuth(server)
        code = await auth.start({"clientId": "...", "scopes": [...]})
        # code.user_code, code.verification_uri are surfaced to the user
        # code.interval is the suggested poll cadence
        result = await auth.poll(code, {"clientId": "..."})  # blocks until ok/err/timeout
    """

    def __init__(self, server: Any) -> None:
        self._server = server

    async def start(self, params: dict[str, Any]) -> dict[str, Any]:
        if not params.get("clientId"):
            raise TwitchOAuthError("Missing Twitch Client ID. Set it in Settings first.")
        try:
            r = await self._server.http.post(
                "/api/twitch/device/start",
                json={
                    "clientId": params["clientId"],
                    "clientSecret": params.get("clientSecret") or None,
                    "scopes": params.get("scopes") or [],
                },
            )
        except Exception as exc:
            raise TwitchOAuthError(f"Could not reach local server: {exc}") from exc

        if r.status_code != 200:
            raise TwitchOAuthError(r.text.strip() or f"HTTP {r.status_code}")

        data = r.json()
        for key in ("deviceCode", "userCode", "verificationUri"):
            if not data.get(key):
                raise TwitchOAuthError(f"Server returned incomplete device code response (missing {key}).")
        return data

    async def poll(
        self,
        code: dict[str, Any],
        params: dict[str, Any],
        *,
        interval: float | None = None,
        timeout: float | None = None,
        on_pending: Any | None = None,
    ) -> dict[str, Any]:
        """Poll until Twitch returns a token, or surfaces a terminal error.

        on_pending can be an awaitable called between polls (handy for posting
        ticker updates without blocking the loop).
        """
        cadence = float(interval or code.get("interval") or 5)
        cadence = max(1.0, cadence)  # Twitch's documented minimum
        deadline = timeout if timeout is not None else float(code.get("expiresIn") or 1800)
        elapsed = 0.0

        while elapsed < deadline:
            try:
                r = await self._server.http.post(
                    "/api/twitch/device/poll",
                    json={
                        "clientId": params["clientId"],
                        "clientSecret": params.get("clientSecret") or None,
                        "deviceCode": code["deviceCode"],
                        "scopes": params.get("scopes") or code.get("scopes") or [],
                    },
                )
            except Exception as exc:
                raise TwitchOAuthError(f"Lost connection to local server: {exc}") from exc

            payload = _response_json(r)
            if payload.get("ok"):
                return payload

            err = _oauth_error_code(payload, r.status_code)
            # Treat server-flagged recoverable errors as transient. Otherwise
            # retry on the canonical RFC 8628 names. Anything else is fatal.
            recoverable_flag = payload.get("recoverable")
            transient = (
                err in ("authorization_pending", "slow_down")
                or recoverable_flag is True
            )
            if transient:
                if err == "slow_down":
                    cadence = min(cadence + 5, 30)
                if on_pending is not None:
                    try:
                        await on_pending(err, elapsed, deadline)
                    except Exception:
                        logger.debug("on_pending callback raised", exc_info=True)
                await asyncio.sleep(cadence)
                elapsed += cadence
                continue

            description = (
                payload.get("errorDescription")
                or payload.get("error_description")
                or payload.get("message")
                or ""
            )
            detail = description or getattr(r, "text", "").strip()
            if r.status_code != 200 and detail and detail != err:
                raise TwitchOAuthError(f"{err}: {detail}")
            raise TwitchOAuthError(f"{err}{(': ' + detail) if detail and detail != err else ''}")

        raise TwitchOAuthError("Device code expired before authorization completed. Try again.")


def open_verification_url(url: str) -> bool:
    """Best-effort: open the URL in the user's default browser.

    Returns True if a browser launch was attempted. We don't wait for the
    process to detach — Twitch's verification page doesn't load anything that
    needs the browser to stay open; the user does the click themselves.
    """
    try:
        return webbrowser.open(url, new=2, autoraise=True)
    except Exception as exc:
        logger.debug("webbrowser.open failed: %s", exc)
        return False
