import pytest
from unittest.mock import patch, MagicMock
from src.connectors.rss import RSSConnector, RSSFeedConfig, make_entry_id


@pytest.fixture
def connector():
    return RSSConnector()


@pytest.fixture
def config():
    return RSSFeedConfig(
        id="test-feed", title="Test Feed",
        feed_url="https://example.com/feed.xml", category="tech",
    )


SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <item>
      <title>Test Post</title>
      <link>https://example.com/post-1</link>
      <guid>https://example.com/post-1</guid>
      <description>This is a test post about interesting things.</description>
      <pubDate>Mon, 31 Mar 2026 12:00:00 GMT</pubDate>
      <author>test@example.com</author>
    </item>
  </channel>
</rss>"""


def test_make_entry_id_deterministic():
    id1 = make_entry_id("feed-a", "guid-1")
    assert len(id1) == 16
    assert make_entry_id("feed-a", "guid-1") == id1
    assert make_entry_id("feed-a", "guid-2") != id1


def test_fetch_success(connector, config):
    with patch("src.connectors.rss.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = SAMPLE_RSS
        mock_resp.headers = {"ETag": '"abc"', "Last-Modified": "Mon, 31 Mar 2026"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = connector.fetch(config)
        assert result.success is True
        assert len(result.data) == 1
        assert result.etag == '"abc"'


def test_fetch_304_not_modified(connector, config):
    config.etag = '"abc"'
    with patch("src.connectors.rss.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 304
        mock_get.return_value = mock_resp

        result = connector.fetch(config)
        assert result.success is True
        assert len(result.data) == 0


def test_normalize(connector, config):
    import feedparser
    feed = feedparser.parse(SAMPLE_RSS)
    entries = connector.normalize(config, feed.entries)
    assert len(entries) == 1
    assert entries[0].title == "Test Post"
    assert entries[0].feed_id == "test-feed"
    assert entries[0].url == "https://example.com/post-1"
    assert entries[0].summary  # has content
