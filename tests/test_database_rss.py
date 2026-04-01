import pytest
from datetime import datetime
from src.storage.database import (
    init_db, upsert_rss_feed, upsert_rss_entry,
    get_rss_entries_by_feed, get_all_rss_feeds,
    update_rss_feed_status, cleanup_old_rss_entries,
    get_all_rss_entries,
)
from src.storage.models import RSSFeed, RSSEntry


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    """Use temp DB for tests."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("src.storage.database.DB_PATH", db_path)
    init_db()


def test_upsert_rss_feed():
    feed = RSSFeed(id="test-feed", title="Test", feed_url="https://example.com/feed")
    upsert_rss_feed(feed)
    feeds = get_all_rss_feeds()
    assert len(feeds) == 1
    assert feeds[0]["id"] == "test-feed"


def test_upsert_rss_entry():
    feed = RSSFeed(id="test-feed", title="Test", feed_url="https://example.com/feed",
                   category="tech")
    upsert_rss_feed(feed)
    entry = RSSEntry(
        id="entry-1", feed_id="test-feed", title="Test Entry",
        url="https://example.com/post", published_at=datetime.now()
    )
    upsert_rss_entry(entry)
    entries = get_rss_entries_by_feed("test-feed")
    assert len(entries) == 1
    assert entries[0]["title"] == "Test Entry"


def test_get_all_rss_entries_joins_feed():
    feed = RSSFeed(id="test-feed", title="My Feed", feed_url="https://example.com/feed",
                   category="tech")
    upsert_rss_feed(feed)
    entry = RSSEntry(id="e1", feed_id="test-feed", title="Post",
                     published_at=datetime.now())
    upsert_rss_entry(entry)
    entries = get_all_rss_entries()
    assert len(entries) == 1
    assert entries[0]["feed_title"] == "My Feed"
    assert entries[0]["category"] == "tech"


def test_update_feed_status():
    feed = RSSFeed(id="test-feed", title="Test", feed_url="https://example.com/feed")
    upsert_rss_feed(feed)
    update_rss_feed_status("test-feed", 200, etag='"abc123"')
    feeds = get_all_rss_feeds()
    assert feeds[0]["last_status"] == 200
    assert feeds[0]["etag"] == '"abc123"'
    assert feeds[0]["error_count"] == 0
