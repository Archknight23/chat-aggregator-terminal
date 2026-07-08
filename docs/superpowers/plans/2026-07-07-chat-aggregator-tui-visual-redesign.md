# Chat Aggregator TUI Visual Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the invisible composer, surface hidden commands, add structural/motion depth, wire up the dead `AlertLog` widget as an alert rail, and neutralize emoji-related rendering risk in the Chat Aggregator TUI.

**Architecture:** Pure CSS/widget-level changes within the existing Textual app (`chat_tui/`) — no new services, no protocol changes. One new pure-Python utility module (`emoji_safe.py`), one new presentational widget (`CommandHints`), and a layout change in `app.py` that splits the main content row into `ChatFeed` + `AlertLog` side by side.

**Tech Stack:** Python 3.11+, Textual (>=0.86.0), Rich, `emoji` (new dependency), pytest/pytest-asyncio (dev, already declared).

## Global Constraints

- Use only colors already defined in `chat_tui/theme.py` (or their raw hex, e.g. `#ffd23f` for `C_YELLOW`) — no new palette colors.
- The `emoji` dependency must be pure Python (no C extension) — required so it doesn't complicate the existing pure-Python dependency set.
- Out of scope (per approved spec, `docs/superpowers/specs/2026-07-07-chat-aggregator-tui-visual-redesign-design.md`): verifying `/api/send/twitch` / `/api/send/kick` against the Node backend, and the missing Kick channel param in `_send_outbound()`.
- `tests/` is currently empty; there is no existing Textual UI test harness in this repo. Per the approved spec, Textual-rendering changes (borders, layout, motion) are verified **manually** with an exact checklist, not via fabricated framework-introspection tests. Only the pure-Python `emoji_safe.demojize()` gets automated pytest coverage — that's the one piece of new logic that's actually safe to assert against without running the full app.
- A virtualenv already exists at `.venv/`. Use `.venv/bin/pip`, `.venv/bin/pytest`, and `.venv/bin/chat-aggregator` for every command below.

---

### Task 1: `emoji_safe` utility + dependency

**Files:**
- Modify: `pyproject.toml`
- Create: `chat_tui/emoji_safe.py`
- Test: `tests/test_emoji_safe.py`

**Interfaces:**
- Produces: `demojize(text: str) -> str` — converts Unicode emoji to `:shortcode:` form; returns falsy input unchanged. Used by Tasks 4, 5, 6.

- [ ] **Step 1: Add the `emoji` dependency**

In `pyproject.toml`, change:

```toml
dependencies = [
    "textual>=0.86.0",
    "httpx>=0.27.0",
    "websockets>=13.0",
    "rich>=13.7.0",
]
```

to:

```toml
dependencies = [
    "textual>=0.86.0",
    "httpx>=0.27.0",
    "websockets>=13.0",
    "rich>=13.7.0",
    "emoji>=2.10.0",
]
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_emoji_safe.py`:

```python
from chat_tui.emoji_safe import demojize


def test_demojize_converts_emoji_to_shortcode():
    assert demojize("nice \U0001F525 stream") == "nice :fire: stream"


def test_demojize_empty_string_returns_empty():
    assert demojize("") == ""


def test_demojize_plain_text_unchanged():
    assert demojize("no emoji here") == "no emoji here"
```

- [ ] **Step 3: Install the new dependency and run the test to verify it fails**

```bash
cd /home/cfsdexpo/projects/chat-aggregator-tui
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/test_emoji_safe.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'chat_tui.emoji_safe'`.

- [ ] **Step 4: Create the implementation**

Create `chat_tui/emoji_safe.py`:

```python
"""Emoji-to-shortcode conversion — prevents double-width Unicode emoji from
breaking Rich/Textual column-width math or rendering as missing-glyph boxes."""

from __future__ import annotations

import emoji as _emoji


def demojize(text: str) -> str:
    if not text:
        return text
    return _emoji.demojize(text, delimiters=(":", ":"))
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
.venv/bin/pytest tests/test_emoji_safe.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml chat_tui/emoji_safe.py tests/test_emoji_safe.py
git commit -m "feat: add emoji_safe.demojize utility to prevent emoji rendering breakage"
```

---

### Task 2: Fix the invisible composer

**Files:**
- Modify: `chat_tui/ui/composer.py`

**Interfaces:**
- No signature changes — CSS-only fix. `Composer` class and its `SendMessage` message keep the same public shape used by `app.py`.

- [ ] **Step 1: Replace the composer's CSS**

In `chat_tui/ui/composer.py`, replace:

```python
    DEFAULT_CSS = """
    Composer {
        height: 3;
        width: 1fr;
        background: $surface;
        border-top: solid $primary;
    }
    Input {
        width: 1fr;
    }
    Button {
        width: 12;
    }
    """
```

with:

```python
    DEFAULT_CSS = """
    Composer {
        height: 3;
        width: 1fr;
        background: $surface;
        border: solid $secondary;
    }
    #composer_input {
        width: 1fr;
        background: $panel;
        color: #e8e8f0;
        border: tall $secondary 50%;
    }
    #composer_input:focus {
        border: tall $secondary;
    }
    #composer_send {
        width: 12;
        background: $secondary;
        color: #0a0a0f;
        text-style: bold;
    }
    """
```

**Note on selectors:** this targets `#composer_input`/`#composer_send` (the IDs already assigned in `compose()` below) rather than bare `Input`/`Button` type selectors. A bare type selector loses the CSS specificity contest against Textual's own built-in `Input`/`Button` `DEFAULT_CSS` (and against the `.-primary` variant class Textual adds for `Button(..., variant="primary")`) — verified empirically: with bare type selectors, `Input.styles.background` resolved to `$surface` (Textual's own Input default) instead of `$panel`, `Input.styles.border` resolved to Textual's stock focus-blue instead of `$secondary`, and `Button.styles.background` resolved to `$primary` (from the `.-primary` variant rule) instead of `$secondary`. ID selectors outrank both and apply reliably. This also avoids the bare `Input` rule leaking onto unrelated `Input` widgets elsewhere in the app (e.g. `SettingsModal`'s fields), since a type selector is unscoped and matches every `Input` in the app.

- [ ] **Step 2: Manually verify against the real app (not a bare scratch app)**

A bare scratch `App` with only `Composer` mounted does **not** reproduce Textual's real CSS cascade (it's missing the app's `$primary`/`$secondary`/`$panel` variable declarations and doesn't exercise cross-widget specificity the way the full app does). Verify against the actual `ChatAggregatorApp` instead:

```bash
cd /home/cfsdexpo/projects/chat-aggregator-tui
.venv/bin/python -c "
import asyncio
from chat_tui.app import ChatAggregatorApp
from chat_tui.ui.composer import Composer

async def main():
    app = ChatAggregatorApp()
    async with app.run_test():
        composer = app.query_one('#composer', Composer)
        input_widget = composer.query_one('Input')
        button_widget = composer.query_one('Button')
        print('Input background:', input_widget.styles.background)
        print('Input border:', input_widget.styles.border)
        print('Button background:', button_widget.styles.background)

asyncio.run(main())
"
```

Expected: `Input background: Color(21, 19, 28)` (`$panel`, `#15131c`), `Input border:` all four edges `Color(255, 107, 26)` (`$secondary`, `#ff6b1a` — the app auto-focuses the input on mount, so this is the `:focus` state), `Button background: Color(255, 107, 26)` (`$secondary`). This is a structural sanity check, not a substitute for the full visual check in Task 8.

Note: `composer.styles.border` will still show a two-toned result at this point (top edge `$primary` purple, other three edges `$secondary` orange) — that's `chat_tui/app.py`'s pre-existing `#composer { border-top: solid $primary; }` ID rule (higher specificity than `Composer`'s own type-selector `border` rule) still in effect. This is expected and resolves itself once Task 8 replaces that rule; it is not something this task can or should fix.

- [ ] **Step 3: Commit**

```bash
git add chat_tui/ui/composer.py
git commit -m "fix: give composer Input/Button explicit colors so they're actually visible"
```

---

### Task 3: `CommandHints` widget

**Files:**
- Create: `chat_tui/ui/command_hints.py`

**Interfaces:**
- Produces: `CommandHints` — a `Static` subclass, height 1, no constructor args beyond standard Textual widget kwargs (`id=`, etc.). Mounted by Task 8.

- [ ] **Step 1: Create the widget**

Create `chat_tui/ui/command_hints.py`:

```python
"""Persistent one-line strip surfacing slash commands and key hints."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

C_HINT_SLASH = "#8a6bb0"
C_HINT_KEY = "#c77a3f"


class CommandHints(Static):
    """Always-visible reference for slash commands and key bindings."""

    DEFAULT_CSS = """
    CommandHints {
        height: 1;
        width: 1fr;
        background: $surface;
        padding: 0 1;
        content-align: left middle;
    }
    """

    def on_mount(self) -> None:
        self.update(self._build_text())

    def _build_text(self) -> Text:
        text = Text()
        text.append(":: ", style="#6b6b7a")
        text.append(
            "/settings  /clear  /raid <channel>  /platform <name>",
            style=C_HINT_SLASH,
        )
        text.append("   ")
        text.append(
            "[tab] switch platform  [s] settings  [c] clear",
            style=C_HINT_KEY,
        )
        return text
```

- [ ] **Step 2: Manually verify it mounts and renders**

```bash
cd /home/cfsdexpo/projects/chat-aggregator-tui
.venv/bin/python -c "
import asyncio
from textual.app import App, ComposeResult
from chat_tui.ui.command_hints import CommandHints

class ScratchApp(App):
    def compose(self) -> ComposeResult:
        yield CommandHints(id='hints')

async def main():
    app = ScratchApp()
    async with app.run_test():
        hints = app.query_one('#hints', CommandHints)
        print('renderable set:', hints.renderable is not None)

asyncio.run(main())
"
```

Expected: `renderable set: True`, no traceback.

- [ ] **Step 3: Commit**

```bash
git add chat_tui/ui/command_hints.py
git commit -m "feat: add persistent CommandHints strip for slash commands and key bindings"
```

---

### Task 4: `ChatMessage` — platform accent border, fade-in, emoji safety

**Files:**
- Modify: `chat_tui/ui/chat_feed.py`

**Interfaces:**
- Consumes: `demojize(text: str) -> str` from `chat_tui/emoji_safe.py` (Task 1).
- No changes to `ChatFeed.add()` / `.clear()` — `app.py`'s calls (`_post_chat`, `action_clear`) are unaffected.

- [ ] **Step 1: Add the platform-accent CSS classes and emoji-safe import**

In `chat_tui/ui/chat_feed.py`, replace the top of the file through the `ChatMessage.DEFAULT_CSS` block:

```python
"""Unified chat feed widget — scrollable message list per platform."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

from chat_tui.emoji_safe import demojize
from chat_tui.theme import C_BG, C_DIM, C_FG, C_SYSTEM, platform_color


class ChatMessage(Widget, can_focus=False):
    """Single chat message row."""

    DEFAULT_CSS = """
    ChatMessage {
        height: auto;
        width: 1fr;
        background: $surface-darken-1;
        margin: 0 0 1 0;
        padding: 0 1;
        border-left: thick #6b6b7a;
    }
    ChatMessage.platform-twitch {
        border-left: thick #a970ff;
    }
    ChatMessage.platform-youtube {
        border-left: thick #ff4444;
    }
    ChatMessage.platform-kick {
        border-left: thick #53fc18;
    }
    ChatMessage.platform-local {
        border-left: thick #ff6b1a;
    }
    """
```

- [ ] **Step 2: Add `on_mount` (platform class + fade-in) and demojize in `render()`**

Replace the `ChatMessage.__init__`/`render` block with:

```python
    def __init__(self, message: dict[str, Any], **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = message

    def on_mount(self) -> None:
        platform = (self.message.get("platform") or "system").lower()
        if platform in ("twitch", "youtube", "kick", "local"):
            self.add_class(f"platform-{platform}")
        self.styles.opacity = 0.0
        self.styles.animate("opacity", value=1.0, duration=0.2)

    def render(self) -> Text:
        msg = self.message
        platform = (msg.get("platform") or "system").lower()
        username = str(msg.get("username") or "—")
        text = demojize(str(msg.get("text") or ""))
        ts = msg.get("timestamp")

        ts_str = ""
        if ts:
            try:
                if isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(ts / 1000.0)
                else:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                ts_str = dt.strftime("%H:%M:%S")
            except Exception:
                ts_str = str(ts)[:8]

        out = Text()
        if ts_str:
            out.append(f"[{ts_str}] ", style=C_DIM)
        out.append(f"{username}: ", style=f"bold {platform_color(platform)}")
        out.append(text, style=C_FG)
        return out
```

`ChatFeed` (the `VerticalScroll` subclass below this in the file) is unchanged — leave it exactly as-is.

- [ ] **Step 3: Manually verify**

```bash
cd /home/cfsdexpo/projects/chat-aggregator-tui
.venv/bin/python -c "
import asyncio
from textual.app import App, ComposeResult
from chat_tui.ui.chat_feed import ChatFeed

class ScratchApp(App):
    def compose(self) -> ComposeResult:
        yield ChatFeed(id='chat_feed')

async def main():
    app = ScratchApp()
    async with app.run_test():
        feed = app.query_one('#chat_feed', ChatFeed)
        feed.add({'username': 'nyxshade', 'text': 'nice \U0001F525 stream', 'platform': 'twitch'})
        await asyncio.sleep(0.1)
        msg = feed.children[0]
        print('classes:', msg.classes)
        print('rendered:', msg.render().plain)

asyncio.run(main())
"
```

Expected: `classes:` includes `platform-twitch`; `rendered:` contains `:fire:`, not the raw emoji glyph.

- [ ] **Step 4: Commit**

```bash
git add chat_tui/ui/chat_feed.py
git commit -m "feat: add platform accent border, fade-in, and emoji-safe text to ChatMessage"
```

---

### Task 5: `StatusTicker` emoji safety

**Files:**
- Modify: `chat_tui/ui/status_ticker.py`

**Interfaces:**
- Consumes: `demojize(text: str) -> str` from Task 1.
- No changes to `StatusTicker.add()` / `.clear()` — `app.py`'s `_post_ticker()` calls are unaffected.

- [ ] **Step 1: Add the import and wrap `body`**

In `chat_tui/ui/status_ticker.py`, change the import block:

```python
from chat_tui.theme import C_DIM, C_FG, severity_color
```

to:

```python
from chat_tui.emoji_safe import demojize
from chat_tui.theme import C_DIM, C_FG, severity_color
```

Then in `_build_text`, change:

```python
        sev = item.get("severity", "info")
        body = str(item.get("text", ""))
```

to:

```python
        sev = item.get("severity", "info")
        body = demojize(str(item.get("text", "")))
```

- [ ] **Step 2: Manually verify**

```bash
cd /home/cfsdexpo/projects/chat-aggregator-tui
.venv/bin/python -c "
import asyncio
from textual.app import App, ComposeResult
from chat_tui.ui.status_ticker import StatusTicker

class ScratchApp(App):
    def compose(self) -> ComposeResult:
        yield StatusTicker(id='ticker')

async def main():
    app = ScratchApp()
    async with app.run_test():
        ticker = app.query_one('#ticker', StatusTicker)
        ticker.add('raid incoming \U0001F389', severity='info')
        print(ticker.render().plain)

asyncio.run(main())
"
```

Expected: output contains `:party_popper:`, not the raw emoji glyph.

- [ ] **Step 3: Commit**

```bash
git add chat_tui/ui/status_ticker.py
git commit -m "fix: demojize ticker text to prevent emoji rendering breakage"
```

---

### Task 6: `AlertLog` emoji safety

**Files:**
- Modify: `chat_tui/ui/alert_log.py`

**Interfaces:**
- Consumes: `demojize(text: str) -> str` from Task 1.
- No changes to `AlertLog.add()` / `.clear()` public shape — Task 8 will call `.add(event)` from `app.py`.

- [ ] **Step 1: Add the import and wrap the alert text**

In `chat_tui/ui/alert_log.py`, change:

```python
from chat_tui.theme import C_DIM, C_FG, severity_color
```

to:

```python
from chat_tui.emoji_safe import demojize
from chat_tui.theme import C_DIM, C_FG, severity_color
```

Then in `AlertRow.render`, change:

```python
    def render(self) -> Text:
        event = self.event
        text = str(event.get("text") or event.get("eventType") or "event")
```

to:

```python
    def render(self) -> Text:
        event = self.event
        text = demojize(str(event.get("text") or event.get("eventType") or "event"))
```

- [ ] **Step 2: Manually verify**

```bash
cd /home/cfsdexpo/projects/chat-aggregator-tui
.venv/bin/python -c "
import asyncio
from textual.app import App, ComposeResult
from chat_tui.ui.alert_log import AlertLog

class ScratchApp(App):
    def compose(self) -> ComposeResult:
        yield AlertLog(id='alert_log')

async def main():
    app = ScratchApp()
    async with app.run_test():
        log = app.query_one('#alert_log', AlertLog)
        log.add({'text': 'REWARD — felruin redeemed Hydrate \U0001F4A7', 'timestamp': None})
        await asyncio.sleep(0.1)
        row = log.children[0]
        print(row.render().plain)

asyncio.run(main())
"
```

Expected: output contains `:droplet:`, not the raw emoji glyph.

- [ ] **Step 3: Commit**

```bash
git add chat_tui/ui/alert_log.py
git commit -m "fix: demojize alert log text to prevent emoji rendering breakage"
```

---

### Task 7: `ViewerBar` connecting-state pulse

**Files:**
- Modify: `chat_tui/ui/viewer_bar.py`

**Interfaces:**
- No public API changes — `update_count()`, `set_connection()`, `clear()` keep their existing signatures, used unchanged by `app.py`.

- [ ] **Step 1: Add the pulse state and timer**

In `chat_tui/ui/viewer_bar.py`, change:

```python
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._label = Label("")

    def compose(self) -> ComposeResult:
        yield self._label

    def on_mount(self) -> None:
        self._refresh_label()
```

to:

```python
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._label = Label("")
        self._pulse_on = True

    def compose(self) -> ComposeResult:
        yield self._label

    def on_mount(self) -> None:
        self._refresh_label()
        self.set_interval(0.5, self._pulse_tick)

    def _pulse_tick(self) -> None:
        if not any(state == ConnState.CONNECTING for state in self.connections.values()):
            return
        self._pulse_on = not self._pulse_on
        self._refresh_label()
```

- [ ] **Step 2: Make the icon style depend on the pulse while CONNECTING**

In `_refresh_label`, change:

```python
            value = self.counts.get(platform)
            conn = self.connections.get(platform, ConnState.DISCONNECTED)
            label = platform.upper()
            icon = conn.icon()
            icon_style = f"bold {conn.color()}"
```

to:

```python
            value = self.counts.get(platform)
            conn = self.connections.get(platform, ConnState.DISCONNECTED)
            label = platform.upper()
            icon = conn.icon()
            if conn == ConnState.CONNECTING:
                icon_style = f"{'bold' if self._pulse_on else 'dim'} {conn.color()}"
            else:
                icon_style = f"bold {conn.color()}"
```

- [ ] **Step 3: Manually verify**

```bash
cd /home/cfsdexpo/projects/chat-aggregator-tui
.venv/bin/python -c "
import asyncio
from textual.app import App, ComposeResult
from chat_tui.ui.viewer_bar import ViewerBar
from chat_tui.conn_state import ConnState

class ScratchApp(App):
    def compose(self) -> ComposeResult:
        yield ViewerBar(id='viewer_bar')

async def main():
    app = ScratchApp()
    async with app.run_test():
        bar = app.query_one('#viewer_bar', ViewerBar)
        bar.set_connection('twitch', ConnState.CONNECTING)
        before = bar._pulse_on
        await asyncio.sleep(0.6)
        after = bar._pulse_on
        print('pulse toggled:', before != after)

asyncio.run(main())
"
```

Expected: `pulse toggled: True`.

- [ ] **Step 4: Commit**

```bash
git add chat_tui/ui/viewer_bar.py
git commit -m "feat: pulse connection dot while a platform is CONNECTING"
```

---

### Task 8: App integration — layout, alert rail wiring, cleanup

**Files:**
- Modify: `chat_tui/app.py`

**Interfaces:**
- Consumes: `CommandHints` (Task 3), `ChatMessage`/`ChatFeed` (Task 4), `AlertLog.add(event: dict) -> None` (already existed, now actually called).
- No changes to `Composer.SendMessage`, `on_composer_send_message`, `_handle_slash`, `_send_outbound`, `_send_raid`, `_bus_pump`, `_apply_settings*`, `_stop_clients`, `_twitch_sse_loop`, `_format_twitch_event`, `_viewer_poll_loop` — none of those are touched by this task.

- [ ] **Step 1: Update imports**

In `chat_tui/app.py`, change:

```python
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static
```

to:

```python
from textual.widgets import Footer, Header
```

(The `reactive` import and `Static` import are both dropped — `reactive` was only used for the `status_text` reactive being removed in Step 3 below, and `Static` was only used for the `#status_bar` widget being removed in Step 2.)

Then change:

```python
from chat_tui.ui.alert_log import AlertLog
from chat_tui.ui.chat_feed import ChatFeed
from chat_tui.ui.composer import Composer
from chat_tui.ui.settings_modal import SettingsModal
from chat_tui.ui.status_ticker import StatusTicker
from chat_tui.ui.viewer_bar import ViewerBar
```

to:

```python
from chat_tui.ui.alert_log import AlertLog
from chat_tui.ui.chat_feed import ChatFeed
from chat_tui.ui.command_hints import CommandHints
from chat_tui.ui.composer import Composer
from chat_tui.ui.settings_modal import SettingsModal
from chat_tui.ui.status_ticker import StatusTicker
from chat_tui.ui.viewer_bar import ViewerBar
```

- [ ] **Step 2: Replace the CSS block**

Replace the entire `CSS = """ ... """` block in `ChatAggregatorApp` with:

```python
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
    #content_row {
        width: 1fr;
        height: 1fr;
    }
    #chat_feed {
        width: 1fr;
        height: 1fr;
        border: solid $primary;
    }
    #alert_log {
        width: 34;
        height: 1fr;
        border: solid #ffd23f;
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
        height: 3;
        background: $panel;
        border: solid $secondary;
    }
    """
```

This drops the dead `#chat_pane` rule (never had a matching widget) and the `#status_bar { display: none; }` rule (the widget itself is being removed in Step 4).

- [ ] **Step 3: Remove the `status_text` reactive**

Change:

```python
    status_text: reactive[str] = reactive(":: CHAT AGGREGATOR TUI")

    def __init__(self, server_url: str = DEFAULT_SERVER_URL, **kwargs) -> None:
```

to:

```python
    def __init__(self, server_url: str = DEFAULT_SERVER_URL, **kwargs) -> None:
```

- [ ] **Step 4: Rewrite `compose()`**

Change:

```python
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="main"):
            yield ViewerBar(id="viewer_bar")
            yield ChatFeed(id="chat_feed")
            yield StatusTicker(id="ticker")
            yield Composer(id="composer")
            yield Static(self.status_text, id="status_bar")
        yield Footer()
```

to:

```python
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
```

- [ ] **Step 5: Feed alerts into the rail**

Change:

```python
    def _post_alert(self, event: dict[str, Any]) -> None:
        text = str(event.get("text") or event.get("eventType") or "event")
        severity = "error" if "error" in str(event.get("eventType", "")).lower() else "info"
        self._post_ticker(text, severity=severity)
```

to:

```python
    def _post_alert(self, event: dict[str, Any]) -> None:
        text = str(event.get("text") or event.get("eventType") or "event")
        severity = "error" if "error" in str(event.get("eventType", "")).lower() else "info"
        self._post_ticker(text, severity=severity)
        self.query_one("#alert_log", AlertLog).add(event)
```

- [ ] **Step 6: Simplify `_set_status`**

Change:

```python
    def _set_status(self, payload: dict[str, Any]) -> None:
        text = payload.get("text", "")
        if text:
            self.status_text = text
            self._post_ticker(text, severity="info")
```

to:

```python
    def _set_status(self, payload: dict[str, Any]) -> None:
        text = payload.get("text", "")
        if text:
            self._post_ticker(text, severity="info")
```

- [ ] **Step 7: Full manual verification pass**

```bash
cd /home/cfsdexpo/projects/chat-aggregator-tui
.venv/bin/pip install -e ".[dev]"
.venv/bin/chat-aggregator
```

With the app running, confirm all of the following, then quit with `q`:

1. **Layout**: `CHAT FEED` (purple border, label in the border line) and `ALERTS` (yellow border, label in the border line) sit side by side, with `CHAT FEED` noticeably wider.
2. **Composer**: a bordered orange box labeled `COMPOSER` at the bottom, containing a visible `LOCAL` label, an outlined input field showing the placeholder text, and a solid orange `SEND` button — not a bare `LOCAL` string on empty background.
3. **Command hints**: a one-line strip above the composer reading `:: /settings  /clear  /raid <channel>  /platform <name>` followed by key hints.
4. **Local send + fade-in + accent border**: type a message, press Enter. It appears in `CHAT FEED` immediately with an orange left-accent bar (platform = local) and a brief fade-in.
5. **Emoji safety**: type a message containing an emoji, e.g. `nice fire test 🔥`, send it, and confirm it renders as `nice fire test :fire:` — no raw glyph, no tofu box, no column misalignment.
6. **Connecting pulse**: press `s`, set a Twitch channel, save. While the connection is resolving, the `TWITCH` dot in the viewer bar alternates bold/dim roughly twice a second; once it settles to connected/error, it stops alternating.
7. **Alert rail**: trigger any alert (a raid/reward event if Twitch events are enabled and connected, or by confirming via `/tmp/chat-aggregator-tui.log` that `_post_alert` fired) and confirm the same text appears both in the one-line ticker *and* persists as a row in `ALERTS` after the ticker moves on to the next thing.
8. Check `/tmp/chat-aggregator-tui.log` for any unhandled exceptions logged during the session.

- [ ] **Step 8: Commit**

```bash
git add chat_tui/app.py
git commit -m "feat: wire up alert rail, mount CommandHints, apply composer/panel titles, drop dead status_bar"
```

---

## Self-Review

**Spec coverage:**
- §1 Structural depth → Tasks 2 (composer border), 4 (chat message accent border), 8 (chat_feed/alert_log/composer `border_title`, CSS borders). ✓
- §2 Composer fix → Task 2. ✓
- §3 Command hint strip → Task 3 + mounted in Task 8. ✓
- §4 Motion → Task 4 (fade-in), Task 7 (connecting pulse). ✓
- §5 Alert rail → Task 6 (demojize) + Task 8 (mount + wire `_post_alert`). ✓
- §6 Emoji safety → Task 1 (utility) + Tasks 4/5/6 (applied at the three render sites). ✓
- Component tree / dead-code cleanup (`#chat_pane`, `#status_bar`, `status_text` reactive) → Task 8. ✓
- Testing/verification → manual checklists per task + Task 1's automated unit tests, matching the approved spec's testing section. ✓
- Follow-ups (Twitch/Kick send verification, Kick channel param) → explicitly listed as out of scope in Global Constraints, not touched by any task. ✓

**Placeholder scan:** No TBD/TODO markers; every step shows exact code or an exact command with expected output.

**Type consistency:** `demojize(text: str) -> str` signature and import path (`chat_tui.emoji_safe`) are identical across Tasks 1, 4, 5, 6. `CommandHints` (no constructor args beyond `id=`) matches its use in Task 8 (`CommandHints(id="hints")`). `AlertLog.add(event: dict[str, Any]) -> None` (pre-existing, unchanged signature) matches its call in Task 8's `_post_alert`. `border_title` is a built-in Textual `Widget` attribute, not something any task needs to define.
