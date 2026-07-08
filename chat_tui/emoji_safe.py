"""Emoji-to-shortcode conversion — prevents double-width Unicode emoji from
breaking Rich/Textual column-width math or rendering as missing-glyph boxes."""

from __future__ import annotations

import emoji as _emoji


def demojize(text: str) -> str:
    if not text:
        return text
    return _emoji.demojize(text, delimiters=(":", ":"))
