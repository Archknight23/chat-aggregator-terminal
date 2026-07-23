from __future__ import annotations

import pytest
from textual.widgets import Button, Input

from chat_tui.app import ChatAggregatorApp
from chat_tui.ui.settings_modal import SettingsModal


@pytest.mark.asyncio
async def test_twitch_client_secret_can_be_revealed_and_hidden() -> None:
    app = ChatAggregatorApp()
    async with app.run_test(size=(140, 50)) as pilot:
        modal = SettingsModal()
        app.push_screen(modal)
        await pilot.pause()

        secret = modal.query_one("#twitchClientSecret", Input)
        toggle = modal.query_one("#twitch_secret_toggle", Button)
        assert secret.password is True
        assert str(toggle.label) == "Show"

        await pilot.click("#twitch_secret_toggle")
        await pilot.pause()
        assert secret.password is False
        assert str(toggle.label) == "Hide"

        app.screen._toggle_secret_visibility()
        await pilot.pause()
        assert secret.password is True
        assert str(toggle.label) == "Show"


@pytest.mark.asyncio
async def test_saved_channel_remains_visible_when_typing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opening Settings must not select-and-replace a saved channel name."""
    from chat_tui import settings

    current = settings.default_settings() | {"twitchChannel": "channel"}
    monkeypatch.setattr(settings, "load_settings", lambda: current.copy())

    app = ChatAggregatorApp()
    app._settings = settings.default_settings()
    async with app.run_test(size=(140, 50)) as pilot:
        modal = SettingsModal()
        app.push_screen(modal)
        await pilot.pause()

        channel = modal.query_one("#twitchChannel", Input)
        original = channel.value
        await pilot.press("s", "c", "t")
        await pilot.pause()

        assert app.screen is modal
        assert channel.value == f"{original}sct"


@pytest.mark.asyncio
async def test_settings_modal_uses_active_app_settings_when_disk_read_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The modal must show the configuration the running client is actually using."""
    from chat_tui import settings

    active = settings.default_settings() | {"twitchChannel": "active-channel"}
    monkeypatch.setattr(settings, "load_settings", settings.default_settings)

    app = ChatAggregatorApp()
    app._settings = active
    async with app.run_test(size=(140, 50)) as pilot:
        modal = SettingsModal()
        app.push_screen(modal)
        await pilot.pause()
        channel = modal.query_one("#twitchChannel", Input)
        assert channel.value == "active-channel"


@pytest.mark.asyncio
async def test_tab_moves_between_settings_fields_not_composer_platform() -> None:
    """Priority Tab must not trap focus on the first settings field."""
    from chat_tui import settings
    from chat_tui.ui.composer import Composer

    app = ChatAggregatorApp()
    app._settings = settings.default_settings() | {
        "twitchChannel": "chaosfoundry",
        "youtubeLiveId": "@Chaosfoundry",
        "kickChannel": "chaosfoundry",
    }
    async with app.run_test(size=(140, 50)) as pilot:
        app.push_screen(SettingsModal())
        await pilot.pause()
        assert app.focused is not None
        assert app.focused.id == "twitchChannel"
        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is not None
        assert app.focused.id == "youtubeLiveId"
        # Composer platform must not cycle while modal owns Tab.
        assert app.query_one("#composer", Composer)._platform == "local"


def test_sanitize_youtube_and_channel_helpers() -> None:
    from chat_tui import settings

    assert settings.sanitize_twitch_channel("#ChaosFoundry") == "chaosfoundry"
    assert settings.sanitize_youtube_target("@Ch@ChChoasfundryaosffoundrydry").startswith("@")
    assert "@" in settings.sanitize_youtube_target("@Chaosfoundry")


def test_chat_feed_url_is_opt_in_not_phone_home() -> None:
    """Missing chatFeedUrl must not inject a production URL."""
    from chat_tui import settings

    assert settings.DEFAULT_CHAT_FEED_URL == ""
    bare = settings.normalize({"twitchChannel": "chaosfoundry"})
    assert bare["chatFeedUrl"] == ""
    explicit = settings.normalize({
        "twitchChannel": "chaosfoundry",
        "chatFeedUrl": "https://chaosfoundry.digital",
    })
    assert explicit["chatFeedUrl"] == "https://chaosfoundry.digital"


def test_chat_feed_url_strips_pasted_endpoint_path() -> None:
    """A pasted .../api/chat/stream URL must reduce to the bare origin.

    remote_feed.py appends its own /api/chat/* suffixes; a leftover path
    here doubles up into a URL that 404s on every request — a fast, silent
    reconnect loop, not an obvious error.
    """
    from chat_tui import settings

    assert settings.sanitize_chat_feed_url("https://chaosfoundry.digital/api/chat/stream") == (
        "https://chaosfoundry.digital"
    )
    assert settings.sanitize_chat_feed_url("https://chaosfoundry.digital/api/chat/recent") == (
        "https://chaosfoundry.digital"
    )
    # Missing slash after scheme (fumbled paste/edit) gets repaired too.
    assert settings.sanitize_chat_feed_url("https:/chaosfoundry.digital/api/chat/stream") == (
        "https://chaosfoundry.digital"
    )
    normalized = settings.normalize({
        "twitchChannel": "chaosfoundry",
        "chatFeedUrl": "https:/chaosfoundry.digital/api/chat/stream",
    })
    assert normalized["chatFeedUrl"] == "https://chaosfoundry.digital"


@pytest.mark.asyncio
async def test_local_ingest_disabled_does_not_leave_platforms_connecting() -> None:
    """Remote-only mode must not paint permanent CONNECTING dots."""
    from chat_tui import settings
    from chat_tui.conn_state import ConnState
    from chat_tui.ui.viewer_bar import ViewerBar

    app = ChatAggregatorApp()
    cfg = settings.default_settings() | {
        "twitchChannel": "chaosfoundry",
        "kickChannel": "chaosfoundry",
        "youtubeLiveId": "@Chaosfoundry",
        "localIngest": False,
        "chatFeedUrl": "",
    }
    async with app.run_test(size=(140, 40)) as pilot:
        await app._apply_settings_async(cfg)
        await pilot.pause()
        bar = app.query_one("#viewer_bar", ViewerBar)
        assert bar.connections.get("twitch") == ConnState.DISCONNECTED
        assert bar.connections.get("kick") == ConnState.DISCONNECTED
        assert bar.connections.get("youtube") == ConnState.DISCONNECTED
        assert app.twitch_irc is None
        assert app.kick is None
