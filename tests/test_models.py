from src.storage.models import RSSFeed, RSSEntry


def test_rss_feed_defaults():
    feed = RSSFeed(id="test", title="Test", feed_url="https://example.com/feed")
    assert feed.tier == "normal"
    assert feed.error_count == 0
    assert feed.category is None


def test_rss_entry_required_fields():
    entry = RSSEntry(id="abc123", feed_id="test", title="Test Entry")
    assert entry.url is None
    assert entry.content is None
    assert entry.word_count is None
