from __future__ import annotations

import asyncio

import pytest

from chat_tui.services.twitch_oauth import TwitchDeviceAuth, activation_url


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict[str, object]:
        return self._payload


class FakeHttp:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.posts: list[tuple[str, dict[str, object]]] = []

    async def post(self, path: str, json: dict[str, object]) -> FakeResponse:
        self.posts.append((path, json))
        return self.responses.pop(0)


class FakeServer:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.http = FakeHttp(responses)


@pytest.mark.asyncio
async def test_poll_keeps_waiting_on_http_400_authorization_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    server = FakeServer(
        [
            FakeResponse(400, {"status": 400, "message": "authorization_pending"}),
            FakeResponse(200, {"ok": True, "status": {"login": "chaosfoundry"}}),
        ]
    )
    pending_states: list[str] = []

    async def on_pending(state: str, _elapsed: float, _total: float) -> None:
        pending_states.append(state)

    result = await TwitchDeviceAuth(server).poll(
        {"deviceCode": "device-code", "interval": 1, "expiresIn": 10},
        {"clientId": "client-id", "scopes": ["channel:read:redemptions"]},
        on_pending=on_pending,
    )

    assert result["ok"] is True
    assert pending_states == ["authorization_pending"]
    assert len(server.http.posts) == 2
    assert server.http.posts[0][1]["scopes"] == ["channel:read:redemptions"]


def test_activation_url_adds_device_code_when_twitch_returns_bare_activate_url() -> None:
    assert (
        activation_url({"verificationUri": "https://www.twitch.tv/activate", "userCode": "ABCDEFGH"})
        == "https://www.twitch.tv/activate?public=true&device-code=ABCDEFGH"
    )


def test_activation_url_preserves_twitch_returned_deep_link() -> None:
    returned = "https://www.twitch.tv/activate?public=true&device-code=ABCDEFGH"
    assert activation_url({"verificationUri": returned, "userCode": "ABCDEFGH"}) == returned
