import httpx
import pytest
from textual.app import App, ComposeResult

from chat_tui.app import ChatAggregatorApp
from chat_tui.services.server_client import ServerClient
from chat_tui.ui.chat_feed import ChatFeed


class FeedApp(App):
    def compose(self) -> ComposeResult:
        yield ChatFeed(id="feed")


@pytest.mark.asyncio
async def test_chat_feed_appends_incrementally_and_stays_bounded() -> None:
    app = FeedApp()
    async with app.run_test() as pilot:
        feed = app.query_one("#feed", ChatFeed)
        feed._max_rows = 3
        for index in range(5):
            feed.add({"id": str(index), "username": "user", "text": str(index)})
        await pilot.pause()

        assert [message["id"] for message in feed.messages] == ["2", "3", "4"]
        assert len(feed.children) == 3


def test_message_deduplication_is_scoped_by_platform() -> None:
    app = ChatAggregatorApp()
    twitch = {"platform": "twitch", "id": "42"}

    assert app._is_duplicate_message(twitch) is False
    assert app._is_duplicate_message(twitch) is True
    assert app._is_duplicate_message({"platform": "youtube", "id": "42"}) is False
    assert app._is_duplicate_message({"platform": "twitch"}) is False


@pytest.mark.asyncio
async def test_viewer_channel_is_encoded_as_one_path_segment() -> None:
    seen_path = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_path
        seen_path = request.url.raw_path.decode()
        return httpx.Response(200, json={"viewers": 7})

    client = ServerClient("http://test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")
    try:
        assert await client.fetch_viewers("youtube", "watch/a?b=c") == 7
    finally:
        await client.stop()

    assert seen_path == "/api/viewers/youtube/watch%2Fa%3Fb%3Dc"
