from chat_tui.emoji_safe import demojize


def test_demojize_converts_emoji_to_shortcode():
    assert demojize("nice \U0001F525 stream") == "nice :fire: stream"


def test_demojize_empty_string_returns_empty():
    assert demojize("") == ""


def test_demojize_plain_text_unchanged():
    assert demojize("no emoji here") == "no emoji here"
