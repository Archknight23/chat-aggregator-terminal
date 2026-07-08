# Chat Aggregator TUI — Visual & UX Redesign

Date: 2026-07-07

## Motivation

Current build (`4902d77`) has three usability problems reported directly against the running app:

1. The composer's `Input` and `Button` are effectively invisible — they inherit Textual design tokens (`$primary-background`, `$panel-lighten-1`, etc.) that this app's CSS never defines, so they render with near-zero contrast against the panel background. Only the platform label (`LOCAL`, a plain `Static`) reads as present.
2. The only discoverable commands are the 4 keybindings with `show=True` in `App.BINDINGS`. The 4 slash commands (`/settings`, `/clear`, `/raid`, `/platform`) exist only inside `_handle_slash()` in `app.py` with zero UI surface.
3. The layout is flat, solid-color blocks with hairline borders — no visual hierarchy or depth versus reference points (`ytm-player`'s discoverable, hover-responsive chrome; `cf-admin`'s bordered, high-contrast neon panels).

Two more requirements were added once the base direction was approved:

4. `AlertLog` (`chat_tui/ui/alert_log.py`) is a fully-implemented scrollable event rail (200-row scrollback, timestamped, severity-colored) that is imported in `app.py` but never mounted or fed — `_post_alert()` only ever writes to the single-line `StatusTicker`. Channel point redeems already format correctly via `_format_twitch_event()`; they just have nowhere persistent to land.
5. Chat text from Twitch/Kick/YouTube can contain arbitrary Unicode emoji. Rich/Textual's column-width math does not reliably account for double-width emoji glyphs, so a message containing one can misalign borders or wrap unexpectedly — independent of whether the terminal font has the glyph at all. This hasn't been observed yet; it's a preventive fix.

Approved direction: retro-cyberpunk, referencing `ytm-player` (intuitive: hover/active states, discoverable commands) and `cf-admin` (cool-looking: full bordered panels, high-contrast focus states, inverted highlights). Confirmed via browser mockup (`.superpowers/brainstorm/3741159-1783471221/content/chat-aggregator-v2.html`).

## Scope

In scope: `chat_tui/app.py` layout wiring, `chat_tui/ui/*` widget CSS and structure, one new widget (`CommandHints`), one new utility module (`emoji_safe.py`), one new dependency (`emoji`).

Out of scope (explicitly deferred by the user): verifying `/api/send/twitch` and `/api/send/kick` actually work against the Node backend in `~/chat-aggregator`, and the missing Kick channel parameter in `_send_outbound()` (`app.py:194-208`). Both are backend/wiring concerns, not visual/UX.

## 1. Structural depth

- `ChatFeed`, `AlertLog`, and `Composer` each get a full CSS `border` (not just `border-top`/`border-bottom`) and a `border_title` set at mount time (Textual's native embedded-border-label feature — no extra widget needed):
  - `ChatFeed` → `border: solid $primary`, title `"CHAT FEED"` (unchanged color, now a full box)
  - `AlertLog` → `border: solid #ffd23f` (existing `C_YELLOW` from `theme.py`, no new variable needed), title `"ALERTS"`
  - `Composer` → `border: solid $secondary`, title `"COMPOSER"`
- `ChatMessage` rows gain a `border-left: thick <platform-color>` accent, driven by adding a CSS class (`platform-twitch`, `platform-kick`, `platform-youtube`, `platform-local`) on mount, colors matching the existing `platform_color()` mapping in `theme.py`. This is the only per-row depth addition — everything else in the row stays as-is to avoid visual noise.
- No new palette colors — `theme.py` already defines the full set (`C_RED`/`C_YELLOW`/`C_GREEN`/`C_BLUE`/platform colors); this uses them structurally (borders, rail) instead of only for severity text.

## 2. Composer fix

Root cause: `composer.py`'s `DEFAULT_CSS` styles the `Composer` container but never sets explicit `background`/`color`/`border` on the child `Input` or `Button`, so both fall back to Textual's built-in theme tokens this app doesn't define.

Fix — explicit CSS in `Composer.DEFAULT_CSS`:

```css
Composer {
    height: 3;
    width: 1fr;
    background: $surface;
    border: solid $secondary;
}
Input {
    width: 1fr;
    background: $panel;
    color: #e8e8f0;
    border: tall $secondary 50%;
}
Input:focus {
    border: tall $secondary;
}
Button {
    width: 12;
    background: $secondary;
    color: #0a0a0f;
    text-style: bold;
}
```

Plus `self.border_title = "COMPOSER"` set on the `Composer` instance. Since `focus_input()` is already called in `on_mount()`, the input shows at full brightness by default; blurring (e.g. after `escape`) dims it to 50%, which now doubles as a visible focus indicator that didn't exist before.

## 3. Command hint strip

New widget `chat_tui/ui/command_hints.py`: `CommandHints(Static)`, height 1, static content (no reactive state — bindings/slash commands are fixed at compile time, so no update path is needed). Rendered once on mount:

```
:: /settings  /clear  /raid <channel>  /platform <name>   [tab] switch platform  [s] settings  [c] clear
```

Slash commands styled `C_DIM`-adjacent dim-purple, keybind hints dim-orange, using the same `":: "` bracket motif the ticker already establishes. Mounted between `StatusTicker` and `Composer` — last thing visible before the input box.

## 4. Motion

Two additions only — scoped to spots where motion communicates a real state change:

- **Connecting pulse**: `ViewerBar.on_mount()` adds `self.set_interval(0.5, self._pulse_tick)`. `_pulse_tick()` no-ops (skips re-render) unless at least one platform is `ConnState.CONNECTING`; when one is, it flips a `_pulse_on` bool and calls `_refresh_label()`, which uses `bold` vs plain style for that platform's icon depending on the flag. Stops mattering automatically once state moves to `CONNECTED`/`ERROR` (icon style stops alternating because the no-op guard kicks back in).
- **Message fade-in**: `ChatMessage.on_mount()` sets `self.styles.opacity = 0.0` then calls `self.styles.animate("opacity", 1.0, duration=0.2)` — built-in Textual style animation, no extra dependency.

## 5. Alert rail (wires up `AlertLog`)

- Layout changes from a single `Vertical` main column to `Vertical(ViewerBar, Horizontal(ChatFeed, AlertLog), StatusTicker, CommandHints, Composer)`.
- `AlertLog` gets `width: 34` (fixed columns) inside that `Horizontal`; `ChatFeed` keeps `width: 1fr` and absorbs the rest.
- `App._post_alert()` currently only calls `_post_ticker()`. Change it to call both `_post_ticker()` (quick glance, matches current behavior) and `self.query_one("#alert_log", AlertLog).add(event)` (persistent scrollback). No change needed to `_format_twitch_event()` — reward/raid text generation already works, it just had nowhere to persist.

## 6. Emoji safety

New module `chat_tui/emoji_safe.py`:

```python
from __future__ import annotations
import emoji as _emoji

def demojize(text: str) -> str:
    if not text:
        return text
    return _emoji.demojize(text, delimiters=(":", ":"))
```

New dependency: `emoji` (pure Python, no C extension) added to `pyproject.toml` `dependencies`.

Applied at the three render choke points, not at ingestion — this guarantees coverage regardless of which producer (Twitch IRC, Kick polling, YouTube, local echo, or any future platform) generated the text, with one line changed per site instead of one per producer:

- `ChatMessage.render()` in `chat_feed.py` — wraps `text = str(msg.get("text") or "")`
- `AlertRow.render()` in `alert_log.py` — wraps the alert `text`
- `StatusTicker._build_text()` in `status_ticker.py` — wraps `body`

Result: `😀` displays as `:grinning_face:` — fixed-width ASCII that cannot misalign Rich/Textual's column math and cannot render as a missing-glyph box in any terminal/font combination.

## Component tree (before → after)

```
Before:                          After:
Header                           Header
Vertical#main                    Vertical#main
  ViewerBar                        ViewerBar
  ChatFeed                         Horizontal#content_row
  StatusTicker                       ChatFeed        (1fr, border+title)
  Composer                           AlertLog        (34 cols, border+title)  [newly mounted]
  Static#status_bar (display:none)   StatusTicker
Footer                                CommandHints    [new]
                                      Composer        (full border+title)
                                  Footer
```

`Static#status_bar` (display:none, fed by the `status_text` reactive) is already dead visually — this touches the same area, so it gets removed as a small adjacent cleanup rather than left in place; `_set_status()` keeps posting to the ticker only.

## Testing / verification

No existing test suite (`tests/` is empty; `pytest`/`pytest-asyncio` are declared as dev deps but unused so far). Plan:

- Manual run (`python -m chat_tui` or the `chat-aggregator` console script) verifying: composer box + input + button visible without settings configured; chat feed and alert rail both show border titles; typing a local message appears immediately (guaranteed-working path, no server dependency); command hint strip visible; a locally-injected Unicode emoji renders as `:shortcode:` text, not a raw glyph or tofu box.
- Triggering `ConnState.CONNECTING` (e.g. pointing at a channel that's slow to resolve) to confirm the pulse is visible and stops once it resolves.
- A small unit test for `emoji_safe.demojize()` (pure function, deterministic) since it's trivial to cover and has no UI/async dependencies.

## Follow-ups (not in this pass)

- Verify `/api/send/twitch` and `/api/send/kick` against the Node backend actually deliver messages (deferred by user).
- Kick channel isn't threaded into `_send_outbound()`'s `channel` param the way Twitch's is (`app.py:194-208`) — likely fine if the server resolves it from session/auth, but unverified.
