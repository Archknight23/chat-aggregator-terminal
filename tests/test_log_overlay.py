from __future__ import annotations

import pytest
from textual.containers import VerticalScroll
from textual.widgets import TabbedContent

from chat_tui.app import ChatAggregatorApp
from chat_tui.ui.log_overlay import LogOverlay
from chat_tui.ui.settings_modal import SettingsModal


@pytest.mark.asyncio
async def test_log_key_opens_tabbed_overlay() -> None:
    app = ChatAggregatorApp()
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.press("f3")
        await pilot.pause()

        assert isinstance(app.screen, LogOverlay)
        tabs = app.screen.query_one("#log_tabs", TabbedContent)
        assert {tab.id for tab in tabs.query("TabPane")} == {"log_tab_status", "log_tab_alerts"}


@pytest.mark.asyncio
async def test_log_overlay_escape_closes_and_restores_main_screen() -> None:
    app = ChatAggregatorApp()
    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.press("f3")
        await pilot.pause()
        assert isinstance(app.screen, LogOverlay)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, LogOverlay)


@pytest.mark.asyncio
async def test_log_key_noop_while_settings_modal_open() -> None:
    """F3 inside Settings must not stack the log overlay on top of it."""
    app = ChatAggregatorApp()
    async with app.run_test(size=(140, 50)) as pilot:
        app.push_screen(SettingsModal())
        await pilot.pause()

        await pilot.press("f3")
        await pilot.pause()

        assert isinstance(app.screen, SettingsModal)


@pytest.mark.asyncio
async def test_l_key_types_into_focused_input_instead_of_opening_log() -> None:
    """Input widgets consume single-character keys before global bindings see them
    (Textual filters "l" out of the priority-binding chain once a focused Input's
    check_consume_key claims it) — same reason Settings needs F2, Log needs F3."""
    from chat_tui.ui.composer import Composer

    app = ChatAggregatorApp()
    async with app.run_test(size=(140, 50)) as pilot:
        assert app.focused is app.query_one("#composer_input")
        await pilot.press("l")
        await pilot.pause()

        assert not isinstance(app.screen, LogOverlay)
        assert "l" in app.query_one("#composer", Composer)._input.value


@pytest.mark.asyncio
async def test_settings_dialog_is_wrapped_in_scroll_container() -> None:
    """Short terminals must scroll the settings form instead of crushing rows."""
    app = ChatAggregatorApp()
    async with app.run_test(size=(140, 15)) as pilot:
        modal = SettingsModal()
        app.push_screen(modal)
        await pilot.pause()

        scroll = modal.query_one("#settings_scroll", VerticalScroll)
        dialog = modal.query_one("#settings_dialog")
        assert dialog in scroll.walk_children()
