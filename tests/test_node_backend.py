from chat_tui.services.node_backend import _port_from_url


def test_port_from_url_uses_explicit_port() -> None:
    assert _port_from_url("http://localhost:4174") == 4174


def test_port_from_url_uses_scheme_default() -> None:
    assert _port_from_url("https://example.test") == 443
