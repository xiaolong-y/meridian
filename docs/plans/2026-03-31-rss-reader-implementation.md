# Meridian RSS Reader — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a full RSS aggregator, manager, and reader to Meridian — with feed timeline, article extraction, and pretext-powered reading pages.

**Architecture:** New `RSSConnector` following `BaseFeedConnector` pattern, new tables in `meridian.db`, CLI tool for feed management (YAML-backed), three generated pages (dashboard card, reader timeline, article pages). Content extracted via trafilatura, rendered with pretext.

**Tech Stack:** feedparser, trafilatura, requests (existing), SQLite (existing), Jinja2 (existing), @chenglou/pretext (CDN)

**Design doc:** `docs/plans/2026-03-31-rss-reader-design.md`

---

## Task 1: Models — RSSFeed and RSSEntry dataclasses

**Files:**
- Modify: `src/storage/models.py`
- Test: `tests/test_models.py`

**Step 1: Add RSSFeed and RSSEntry dataclasses to models.py**

Add after the existing `MetricMeta` class:

```python
@dataclass
class RSSFeed:
    """An RSS feed subscription."""
    id: str                              # slug: 'scott-aaronson'
    title: str
    feed_url: str
    site_url: Optional[str] = None
    category: Optional[str] = None       # 'quantum', 'tech', 'economics'
    tier: str = "normal"                 # 'curated' | 'discovery'
    etag: Optional[str] = None           # conditional GET
    last_modified: Optional[str] = None  # conditional GET
    last_fetched_at: Optional[datetime] = None
    last_status: Optional[int] = None    # HTTP status code
    error_count: int = 0
    created_at: Optional[datetime] = None


@dataclass
class RSSEntry:
    """An entry from an RSS feed."""
    id: str                              # hash of (feed_id, guid or link)
    feed_id: str
    title: str
    url: Optional[str] = None
    guid: Optional[str] = None
    summary: Optional[str] = None        # feed-provided summary
    content: Optional[str] = None        # extracted full article text
    content_hash: Optional[str] = None   # detect content changes
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    word_count: Optional[int] = None
    read_time_minutes: Optional[int] = None
```

**Step 2: Write test to verify models instantiate**

```python
# tests/test_models.py
from src.storage.models import RSSFeed, RSSEntry

def test_rss_feed_defaults():
    feed = RSSFeed(id="test", title="Test", feed_url="https://example.com/feed")
    assert feed.tier == "normal"
    assert feed.error_count == 0

def test_rss_entry_required_fields():
    entry = RSSEntry(id="abc123", feed_id="test", title="Test Entry")
    assert entry.url is None
    assert entry.content is None
```

**Step 3: Run tests**

```bash
pytest tests/test_models.py -v
```

**Step 4: Commit**

```bash
git add src/storage/models.py tests/test_models.py
git commit -m "feat(rss): add RSSFeed and RSSEntry dataclasses"
```

---

## Task 2: Database — RSS tables and CRUD functions

**Files:**
- Modify: `src/storage/database.py`
- Test: `tests/test_database_rss.py`

**Step 1: Add RSS table creation to `init_db()`**

Add these CREATE TABLE statements inside `init_db()` after the existing tables:

```python
# RSS feed subscriptions
cursor.execute("""
    CREATE TABLE IF NOT EXISTS rss_feeds (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        feed_url TEXT NOT NULL UNIQUE,
        site_url TEXT,
        category TEXT,
        tier TEXT DEFAULT 'normal',
        etag TEXT,
        last_modified TEXT,
        last_fetched_at TEXT,
        last_status INTEGER,
        error_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    )
""")

# RSS feed entries
cursor.execute("""
    CREATE TABLE IF NOT EXISTS rss_entries (
        id TEXT PRIMARY KEY,
        feed_id TEXT NOT NULL,
        guid TEXT,
        title TEXT NOT NULL,
        url TEXT,
        summary TEXT,
        content TEXT,
        content_hash TEXT,
        author TEXT,
        published_at TEXT,
        fetched_at TEXT DEFAULT (datetime('now')),
        word_count INTEGER,
        read_time_minutes INTEGER
    )
""")
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_rss_entries_feed
        ON rss_entries(feed_id)
""")
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_rss_entries_published
        ON rss_entries(published_at DESC)
""")

# Saved RSS entries (read-later)
cursor.execute("""
    CREATE TABLE IF NOT EXISTS rss_saved (
        entry_id TEXT PRIMARY KEY,
        saved_at TEXT DEFAULT (datetime('now')),
        note TEXT
    )
""")
```

**Step 2: Add CRUD functions**

```python
def upsert_rss_feed(feed: "RSSFeed") -> None:
    """Insert or update an RSS feed subscription."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO rss_feeds (id, title, feed_url, site_url, category, tier, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                feed_url=excluded.feed_url,
                site_url=excluded.site_url,
                category=excluded.category,
                tier=excluded.tier
        """, (feed.id, feed.title, feed.feed_url, feed.site_url,
              feed.category, feed.tier))


def update_rss_feed_status(feed_id: str, status: int,
                           etag: str = None, last_modified: str = None) -> None:
    """Update feed polling status after fetch."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE rss_feeds SET
                last_status = ?,
                etag = COALESCE(?, etag),
                last_modified = COALESCE(?, last_modified),
                last_fetched_at = datetime('now'),
                error_count = CASE WHEN ? < 400 THEN 0 ELSE error_count + 1 END
            WHERE id = ?
        """, (status, etag, last_modified, status, feed_id))


def upsert_rss_entry(entry: "RSSEntry") -> None:
    """Insert or update an RSS entry."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO rss_entries
                (id, feed_id, guid, title, url, summary, content,
                 content_hash, author, published_at, fetched_at,
                 word_count, read_time_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                summary=excluded.summary,
                content=COALESCE(excluded.content, content),
                content_hash=COALESCE(excluded.content_hash, content_hash),
                word_count=COALESCE(excluded.word_count, word_count),
                read_time_minutes=COALESCE(excluded.read_time_minutes, read_time_minutes)
        """, (entry.id, entry.feed_id, entry.guid, entry.title,
              entry.url, entry.summary, entry.content,
              entry.content_hash, entry.author,
              entry.published_at.isoformat() if entry.published_at else None,
              entry.word_count, entry.read_time_minutes))


def get_rss_entries_by_feed(feed_id: str, limit: int = 20) -> list[dict]:
    """Get RSS entries for a specific feed."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM rss_entries
            WHERE feed_id = ?
            ORDER BY published_at DESC
            LIMIT ?
        """, (feed_id, limit)).fetchall()
        return [dict(r) for r in rows]


def get_rss_entries_by_category(category: str, limit: int = 20) -> list[dict]:
    """Get RSS entries for a category (joins with rss_feeds)."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT e.*, f.title as feed_title, f.category, f.tier, f.site_url
            FROM rss_entries e
            JOIN rss_feeds f ON e.feed_id = f.id
            WHERE f.category = ?
            ORDER BY e.published_at DESC
            LIMIT ?
        """, (category, limit)).fetchall()
        return [dict(r) for r in rows]


def get_all_rss_entries(limit: int = 100) -> list[dict]:
    """Get all RSS entries with feed metadata for reader page."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT e.*, f.title as feed_title, f.category, f.tier, f.site_url
            FROM rss_entries e
            JOIN rss_feeds f ON e.feed_id = f.id
            ORDER BY e.published_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_all_rss_feeds() -> list[dict]:
    """Get all RSS feed subscriptions."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM rss_feeds ORDER BY category, title
        """).fetchall()
        return [dict(r) for r in rows]


def get_rss_entry(entry_id: str) -> dict | None:
    """Get a single RSS entry by ID."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT e.*, f.title as feed_title, f.category, f.tier, f.site_url
            FROM rss_entries e
            JOIN rss_feeds f ON e.feed_id = f.id
            WHERE e.id = ?
        """, (entry_id,)).fetchone()
        return dict(row) if row else None


def cleanup_old_rss_entries(days: int = 30) -> int:
    """Remove RSS entries older than N days (except saved). Returns count."""
    with get_connection() as conn:
        cursor = conn.execute("""
            DELETE FROM rss_entries
            WHERE fetched_at < datetime('now', ? || ' days')
            AND id NOT IN (SELECT entry_id FROM rss_saved)
        """, (f"-{days}",))
        return cursor.rowcount
```

**Step 3: Write tests**

```python
# tests/test_database_rss.py
import pytest
from datetime import datetime
from src.storage.database import (
    init_db, upsert_rss_feed, upsert_rss_entry,
    get_rss_entries_by_feed, get_all_rss_feeds,
    update_rss_feed_status, cleanup_old_rss_entries,
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
    feed = RSSFeed(id="test-feed", title="Test", feed_url="https://example.com/feed")
    upsert_rss_feed(feed)
    entry = RSSEntry(
        id="entry-1", feed_id="test-feed", title="Test Entry",
        url="https://example.com/post", published_at=datetime.now()
    )
    upsert_rss_entry(entry)
    entries = get_rss_entries_by_feed("test-feed")
    assert len(entries) == 1
    assert entries[0]["title"] == "Test Entry"

def test_update_feed_status():
    feed = RSSFeed(id="test-feed", title="Test", feed_url="https://example.com/feed")
    upsert_rss_feed(feed)
    update_rss_feed_status("test-feed", 200, etag='"abc123"')
    feeds = get_all_rss_feeds()
    assert feeds[0]["last_status"] == 200
    assert feeds[0]["etag"] == '"abc123"'
```

**Step 4: Run tests**

```bash
pytest tests/test_database_rss.py -v
```

**Step 5: Commit**

```bash
git add src/storage/database.py tests/test_database_rss.py
git commit -m "feat(rss): add database tables and CRUD for RSS feeds/entries"
```

---

## Task 3: RSSConnector — feedparser + conditional GET

**Files:**
- Create: `src/connectors/rss.py`
- Modify: `src/connectors/__init__.py` (add export)
- Test: `tests/test_rss_connector.py`

**Step 1: Create RSSFeedConfig dataclass and RSSConnector**

```python
# src/connectors/rss.py
"""RSS/Atom feed connector using feedparser."""
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime
from time import mktime
from typing import Any, Optional

import feedparser
import requests

from src.connectors.base import BaseFeedConnector, FetchResult
from src.storage.models import RSSEntry

logger = logging.getLogger(__name__)


@dataclass
class RSSFeedConfig:
    """Configuration for an RSS feed."""
    id: str
    title: str
    feed_url: str
    site_url: Optional[str] = None
    category: Optional[str] = None
    tier: str = "normal"
    limit: int = 50
    # Conditional GET state (loaded from DB)
    etag: Optional[str] = None
    last_modified: Optional[str] = None


def make_entry_id(feed_id: str, guid: str) -> str:
    """Generate a stable entry ID from feed_id + guid."""
    raw = f"{feed_id}:{guid}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class RSSConnector(BaseFeedConnector):
    """RSS/Atom feed connector.

    Uses feedparser for parsing.
    Implements conditional GET via ETag/Last-Modified.
    """

    SOURCE_NAME = "rss"

    def fetch(self, config: RSSFeedConfig) -> FetchResult:
        """Fetch feed with conditional GET."""
        headers = {"User-Agent": "Meridian/1.0 (RSS Reader)"}
        if config.etag:
            headers["If-None-Match"] = config.etag
        if config.last_modified:
            headers["If-Modified-Since"] = config.last_modified

        try:
            resp = requests.get(config.feed_url, headers=headers, timeout=30)

            if resp.status_code == 304:
                logger.info(f"  {config.id}: not modified (304)")
                return FetchResult(
                    success=True, data=[],
                    source=self.SOURCE_NAME
                )

            resp.raise_for_status()
            feed = feedparser.parse(resp.content)

            # Extract caching headers for next fetch
            new_etag = resp.headers.get("ETag")
            new_last_modified = resp.headers.get("Last-Modified")

            return FetchResult(
                success=True,
                data=feed.entries[:config.limit],
                source=self.SOURCE_NAME,
                # Attach caching headers as metadata
                etag=new_etag,
                last_modified=new_last_modified,
                status_code=resp.status_code,
            )

        except requests.RequestException as e:
            logger.error(f"  {config.id}: fetch failed — {e}")
            return FetchResult(
                success=False, data=[],
                error=str(e), source=self.SOURCE_NAME
            )

    def normalize(self, config: RSSFeedConfig, raw_data: list[Any]) -> list[RSSEntry]:
        """Convert feedparser entries to RSSEntry objects."""
        entries = []

        for item in raw_data:
            # Build a stable unique ID
            guid = item.get("id") or item.get("link") or item.get("title", "")
            entry_id = make_entry_id(config.id, guid)

            # Parse published date
            published_at = None
            if item.get("published_parsed"):
                try:
                    published_at = datetime.fromtimestamp(
                        mktime(item.published_parsed)
                    )
                except (ValueError, OverflowError, TypeError):
                    pass
            if not published_at and item.get("updated_parsed"):
                try:
                    published_at = datetime.fromtimestamp(
                        mktime(item.updated_parsed)
                    )
                except (ValueError, OverflowError, TypeError):
                    pass

            # Extract summary (prefer content, fall back to summary)
            summary = ""
            if item.get("content"):
                summary = item.content[0].get("value", "")
            elif item.get("summary"):
                summary = item.summary
            # Strip HTML tags for plain text summary
            if summary:
                import re
                summary = re.sub(r"<[^>]+>", "", summary)
                summary = summary[:500]  # Truncate for dashboard

            # Word count estimate
            word_count = len(summary.split()) if summary else None
            read_time = (word_count // 200) + 1 if word_count else None

            entry = RSSEntry(
                id=entry_id,
                feed_id=config.id,
                guid=guid,
                title=item.get("title", "Untitled"),
                url=item.get("link"),
                summary=summary,
                author=item.get("author"),
                published_at=published_at,
                fetched_at=datetime.now(),
                word_count=word_count,
                read_time_minutes=read_time,
                content_hash=hashlib.md5(
                    summary.encode()
                ).hexdigest() if summary else None,
            )
            entries.append(entry)

        return entries
```

**Step 2: Extend FetchResult to carry HTTP metadata**

In `src/connectors/base.py`, add optional fields to FetchResult:

```python
@dataclass
class FetchResult:
    """Result of a fetch operation."""
    success: bool
    data: list[Any]
    error: Optional[str] = None
    source: str = ""
    fetched_at: datetime = None
    # HTTP caching metadata (used by RSS connector)
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    status_code: Optional[int] = None

    def __post_init__(self):
        if self.fetched_at is None:
            self.fetched_at = datetime.now()
```

**Step 3: Write tests**

```python
# tests/test_rss_connector.py
import pytest
from unittest.mock import patch, MagicMock
from src.connectors.rss import RSSConnector, RSSFeedConfig, make_entry_id


@pytest.fixture
def connector():
    return RSSConnector()


@pytest.fixture
def config():
    return RSSFeedConfig(
        id="test-feed",
        title="Test Feed",
        feed_url="https://example.com/feed.xml",
        category="tech",
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


def test_make_entry_id():
    id1 = make_entry_id("feed-a", "guid-1")
    id2 = make_entry_id("feed-a", "guid-2")
    assert id1 != id2
    assert len(id1) == 16
    # Deterministic
    assert make_entry_id("feed-a", "guid-1") == id1


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
```

**Step 4: Run tests**

```bash
pip install feedparser && pytest tests/test_rss_connector.py -v
```

**Step 5: Commit**

```bash
git add src/connectors/rss.py src/connectors/base.py tests/test_rss_connector.py
git commit -m "feat(rss): add RSSConnector with feedparser + conditional GET"
```

---

## Task 4: Content extraction with trafilatura

**Files:**
- Create: `src/connectors/extractor.py`
- Test: `tests/test_extractor.py`

**Step 1: Create article extractor module**

```python
# src/connectors/extractor.py
"""Article content extraction using trafilatura."""
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def extract_article(url: str, timeout: int = 15) -> Optional[str]:
    """Fetch and extract article text from a URL.

    Returns plain text content or None if extraction fails.
    """
    if not url:
        return None

    try:
        import trafilatura

        resp = requests.get(
            url,
            headers={"User-Agent": "Meridian/1.0 (RSS Reader)"},
            timeout=timeout,
        )
        resp.raise_for_status()

        text = trafilatura.extract(
            resp.text,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            favor_recall=True,
        )
        return text

    except ImportError:
        logger.warning("trafilatura not installed — skipping content extraction")
        return None
    except requests.RequestException as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Failed to extract content from {url}: {e}")
        return None
```

**Step 2: Write test**

```python
# tests/test_extractor.py
from unittest.mock import patch, MagicMock
from src.connectors.extractor import extract_article


def test_extract_article_returns_none_for_empty_url():
    assert extract_article(None) is None
    assert extract_article("") is None


def test_extract_article_handles_request_error():
    with patch("src.connectors.extractor.requests.get") as mock_get:
        mock_get.side_effect = Exception("Connection error")
        result = extract_article("https://example.com/post")
        assert result is None
```

**Step 3: Run tests, commit**

```bash
pip install trafilatura && pytest tests/test_extractor.py -v
git add src/connectors/extractor.py tests/test_extractor.py
git commit -m "feat(rss): add article content extraction with trafilatura"
```

---

## Task 5: Configuration + seed feeds

**Files:**
- Create: `config/rss_feeds.yaml`
- Modify: `pyproject.toml` (add feedparser, trafilatura deps)

**Step 1: Create seed config with quantum computing feeds**

```yaml
# config/rss_feeds.yaml
# RSS feed subscriptions — managed via 'python -m src.rss' CLI
# Feeds are fetched every 6 hours via GitHub Actions

rss_feeds:
  # === Quantum Computing Researchers ===
  - id: scott-aaronson
    title: "Shtetl-Optimized"
    feed_url: https://scottaaronson.blog/?feed=rss2
    site_url: https://scottaaronson.blog
    category: quantum
    tier: curated

  - id: quantum-computing-report
    title: "Quantum Computing Report"
    feed_url: https://quantumcomputingreport.com/feed/
    site_url: https://quantumcomputingreport.com
    category: quantum
    tier: curated

  - id: qiskit-blog
    title: "Qiskit Blog"
    feed_url: https://www.ibm.com/quantum/blog/rss
    site_url: https://www.ibm.com/quantum/blog
    category: quantum
    tier: curated

  - id: quantum-frontiers
    title: "Quantum Frontiers (Caltech)"
    feed_url: https://quantumfrontiers.com/feed/
    site_url: https://quantumfrontiers.com
    category: quantum
    tier: curated

  - id: microsoft-quantum
    title: "Microsoft Quantum Blog"
    feed_url: https://cloudblogs.microsoft.com/quantum/feed/
    site_url: https://cloudblogs.microsoft.com/quantum
    category: quantum
    tier: curated

display:
  entries_per_category: 8
  max_age_days: 7
  article_retention_days: 30
```

**Step 2: Add dependencies to pyproject.toml**

Add to `[project] dependencies`:
```
"feedparser>=6.0",
"trafilatura>=1.6.0",
```

**Step 3: Install and commit**

```bash
pip install feedparser trafilatura
git add config/rss_feeds.yaml pyproject.toml
git commit -m "feat(rss): add seed feeds config (quantum computing) and dependencies"
```

---

## Task 6: CLI tool — feed management

**Files:**
- Create: `src/rss.py`
- Test: `tests/test_rss_cli.py`

**Step 1: Create CLI module**

```python
# src/rss.py
"""RSS feed management CLI.

Usage:
    python -m src.rss add <url>        # discover feed, add to config
    python -m src.rss list             # list all feeds
    python -m src.rss remove <id>      # remove feed from config
    python -m src.rss import <opml>    # import OPML file
    python -m src.rss export           # export feeds as OPML
    python -m src.rss fetch            # manually fetch all feeds
"""
import argparse
import logging
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

logger = logging.getLogger(__name__)
CONFIG_PATH = Path(__file__).parent.parent / "config" / "rss_feeds.yaml"

# Well-known feed paths to probe
FEED_PATHS = [
    "/feed", "/feed/", "/rss", "/rss/", "/atom.xml",
    "/feed.xml", "/index.xml", "/rss.xml", "/feed.json",
    "/feed/rss2/", "/feed/atom/",
]


def _load_config() -> dict:
    """Load RSS feeds config."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_config(config: dict) -> None:
    """Save RSS feeds config."""
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:50].strip("-")


def discover_feed(url: str) -> list[dict]:
    """Discover RSS/Atom feed URLs from a website URL.

    Returns list of {url, type, title} dicts.
    """
    feeds = []

    try:
        resp = requests.get(url, timeout=15,
                           headers={"User-Agent": "Meridian/1.0"})
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")

        # If URL is already a feed
        if "xml" in content_type or "rss" in content_type or "atom" in content_type:
            import feedparser
            parsed = feedparser.parse(resp.content)
            title = parsed.feed.get("title", urlparse(url).hostname)
            return [{"url": url, "type": "rss", "title": title}]

        # Parse HTML for <link rel="alternate"> tags
        html = resp.text
        link_pattern = re.compile(
            r'<link[^>]+rel=["\']alternate["\'][^>]*>',
            re.IGNORECASE
        )
        for match in link_pattern.finditer(html):
            tag = match.group()
            href_match = re.search(r'href=["\']([^"\']+)', tag)
            type_match = re.search(r'type=["\']([^"\']+)', tag)
            title_match = re.search(r'title=["\']([^"\']+)', tag)

            if href_match and type_match:
                feed_type = type_match.group(1)
                if "rss" in feed_type or "atom" in feed_type or "feed" in feed_type:
                    feed_url = href_match.group(1)
                    # Resolve relative URLs
                    if feed_url.startswith("/"):
                        parsed_url = urlparse(url)
                        feed_url = f"{parsed_url.scheme}://{parsed_url.netloc}{feed_url}"
                    feeds.append({
                        "url": feed_url,
                        "type": feed_type,
                        "title": title_match.group(1) if title_match else None,
                    })

        # Probe well-known paths if nothing found
        if not feeds:
            parsed_url = urlparse(url)
            base = f"{parsed_url.scheme}://{parsed_url.netloc}"
            for path in FEED_PATHS:
                try:
                    probe = requests.head(base + path, timeout=5, allow_redirects=True)
                    ct = probe.headers.get("content-type", "")
                    if probe.status_code == 200 and ("xml" in ct or "rss" in ct):
                        feeds.append({"url": base + path, "type": "rss", "title": None})
                        break
                except requests.RequestException:
                    continue

    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)

    return feeds


def cmd_add(url: str) -> None:
    """Add a feed by URL (with discovery)."""
    print(f"Discovering feeds at {url}...")
    feeds = discover_feed(url)

    if not feeds:
        print("No RSS/Atom feeds found at that URL.", file=sys.stderr)
        sys.exit(1)

    # Pick the first discovered feed
    feed = feeds[0]
    feed_url = feed["url"]

    # Fetch feed to get title
    import feedparser
    parsed = feedparser.parse(feed_url)
    title = feed.get("title") or parsed.feed.get("title") or urlparse(url).hostname
    site_url = parsed.feed.get("link") or url
    slug = _slugify(title)

    print(f"  Found: {feed_url}")
    print(f"  Title: {title}")

    # Prompt for category
    category = input("  Category [tech/economics/quantum/blogs/other]: ").strip() or "other"

    # Load config and append
    config = _load_config()
    if "rss_feeds" not in config:
        config["rss_feeds"] = []

    # Check for duplicates
    for existing in config["rss_feeds"]:
        if existing.get("feed_url") == feed_url:
            print(f"  Feed already exists as '{existing['id']}'")
            return

    config["rss_feeds"].append({
        "id": slug,
        "title": title,
        "feed_url": feed_url,
        "site_url": site_url,
        "category": category,
        "tier": "curated",
    })
    _save_config(config)
    print(f"  Added '{slug}' to {CONFIG_PATH.name}")


def cmd_list() -> None:
    """List all configured feeds."""
    config = _load_config()
    feeds = config.get("rss_feeds", [])
    if not feeds:
        print("No feeds configured.")
        return

    # Header
    print(f"  {'ID':<25} {'Category':<12} {'Tier':<10} URL")
    print(f"  {'─'*25} {'─'*12} {'─'*10} {'─'*40}")
    for f in feeds:
        print(f"  {f['id']:<25} {f.get('category',''):<12} {f.get('tier','normal'):<10} {f['feed_url']}")


def cmd_remove(feed_id: str) -> None:
    """Remove a feed by ID."""
    config = _load_config()
    feeds = config.get("rss_feeds", [])
    original_count = len(feeds)
    config["rss_feeds"] = [f for f in feeds if f["id"] != feed_id]
    if len(config["rss_feeds"]) == original_count:
        print(f"Feed '{feed_id}' not found.", file=sys.stderr)
        sys.exit(1)
    _save_config(config)
    print(f"  Removed '{feed_id}'")


def cmd_import_opml(opml_path: str) -> None:
    """Import feeds from an OPML file."""
    tree = ET.parse(opml_path)
    root = tree.getroot()
    config = _load_config()
    if "rss_feeds" not in config:
        config["rss_feeds"] = []

    existing_urls = {f["feed_url"] for f in config["rss_feeds"]}
    count = 0

    for outline in root.iter("outline"):
        xml_url = outline.get("xmlUrl")
        if not xml_url or xml_url in existing_urls:
            continue

        title = outline.get("title") or outline.get("text") or urlparse(xml_url).hostname
        html_url = outline.get("htmlUrl")
        # Use parent outline's text as category
        parent = outline.find("..")
        category = "other"
        if parent is not None and parent.tag == "outline":
            category = _slugify(parent.get("text", "other"))

        config["rss_feeds"].append({
            "id": _slugify(title),
            "title": title,
            "feed_url": xml_url,
            "site_url": html_url,
            "category": category,
            "tier": "curated",
        })
        existing_urls.add(xml_url)
        count += 1

    _save_config(config)
    print(f"  Imported {count} feeds from {opml_path}")


def cmd_export() -> None:
    """Export feeds as OPML to stdout."""
    config = _load_config()
    feeds = config.get("rss_feeds", [])

    print('<?xml version="1.0" encoding="UTF-8"?>')
    print('<opml version="2.0">')
    print("  <head><title>Meridian Feeds</title></head>")
    print("  <body>")

    # Group by category
    categories = {}
    for f in feeds:
        cat = f.get("category", "other")
        categories.setdefault(cat, []).append(f)

    for cat, cat_feeds in categories.items():
        print(f'    <outline text="{cat}" title="{cat}">')
        for f in cat_feeds:
            title = f.get("title", "").replace('"', "&quot;")
            print(f'      <outline type="rss" text="{title}" '
                  f'title="{title}" xmlUrl="{f["feed_url"]}" '
                  f'htmlUrl="{f.get("site_url", "")}"/>')
        print("    </outline>")

    print("  </body>")
    print("</opml>")


def cmd_fetch() -> None:
    """Manually trigger a feed fetch."""
    from src.storage.database import init_db
    from src.main import fetch_rss
    init_db()
    config = _load_config()
    fetch_rss(config)
    print("  Feed fetch complete.")


def main():
    parser = argparse.ArgumentParser(description="Meridian RSS feed manager")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List all feeds")
    add_p = sub.add_parser("add", help="Add a feed by URL")
    add_p.add_argument("url", help="Website or feed URL")
    rm_p = sub.add_parser("remove", help="Remove a feed")
    rm_p.add_argument("id", help="Feed ID to remove")
    imp_p = sub.add_parser("import", help="Import OPML file")
    imp_p.add_argument("file", help="Path to OPML file")
    sub.add_parser("export", help="Export feeds as OPML")
    sub.add_parser("fetch", help="Fetch all feeds now")

    args = parser.parse_args()
    if args.command == "add":
        cmd_add(args.url)
    elif args.command == "list":
        cmd_list()
    elif args.command == "remove":
        cmd_remove(args.id)
    elif args.command == "import":
        cmd_import_opml(args.file)
    elif args.command == "export":
        cmd_export()
    elif args.command == "fetch":
        cmd_fetch()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

**Step 2: Write test for feed discovery**

```python
# tests/test_rss_cli.py
from src.rss import _slugify, _load_config

def test_slugify():
    assert _slugify("Scott Aaronson's Blog!") == "scott-aaronsons-blog"
    assert _slugify("Quantum Computing Report") == "quantum-computing-report"
```

**Step 3: Run tests, commit**

```bash
pytest tests/test_rss_cli.py -v
git add src/rss.py tests/test_rss_cli.py
git commit -m "feat(rss): add CLI tool for feed management (add/list/remove/import/export)"
```

---

## Task 7: Orchestrator integration — fetch_rss in main.py

**Files:**
- Modify: `src/main.py`

**Step 1: Add `fetch_rss()` function and wire into main()**

Add the import at the top of main.py:
```python
from src.connectors.rss import RSSConnector, RSSFeedConfig
from src.connectors.extractor import extract_article
from src.storage.database import (
    upsert_rss_feed, upsert_rss_entry, update_rss_feed_status,
    cleanup_old_rss_entries, get_all_rss_feeds,
)
from src.storage.models import RSSFeed
```

Add the `fetch_rss()` function:
```python
def fetch_rss(rss_config: dict) -> None:
    """Fetch all configured RSS feeds."""
    connector = RSSConnector()
    feeds = rss_config.get("rss_feeds", [])
    display = rss_config.get("display", {})

    logger.info(f"Fetching {len(feeds)} RSS feeds...")

    for feed_def in feeds:
        feed_id = feed_def["id"]
        logger.info(f"  {feed_id}...")

        # Upsert feed record
        feed = RSSFeed(
            id=feed_id,
            title=feed_def["title"],
            feed_url=feed_def["feed_url"],
            site_url=feed_def.get("site_url"),
            category=feed_def.get("category"),
            tier=feed_def.get("tier", "normal"),
        )
        upsert_rss_feed(feed)

        # Load conditional GET state from DB
        db_feeds = {f["id"]: f for f in get_all_rss_feeds()}
        db_feed = db_feeds.get(feed_id, {})

        config = RSSFeedConfig(
            id=feed_id,
            title=feed_def["title"],
            feed_url=feed_def["feed_url"],
            site_url=feed_def.get("site_url"),
            category=feed_def.get("category"),
            tier=feed_def.get("tier", "normal"),
            limit=feed_def.get("limit", 50),
            etag=db_feed.get("etag"),
            last_modified=db_feed.get("last_modified"),
        )

        try:
            result = connector.fetch(config)

            if result.success and result.data:
                entries = connector.normalize(config, result.data)

                # Extract article content for each entry
                for entry in entries:
                    if entry.url:
                        content = extract_article(entry.url)
                        if content:
                            entry.content = content
                            entry.word_count = len(content.split())
                            entry.read_time_minutes = (entry.word_count // 200) + 1

                    upsert_rss_entry(entry)

                logger.info(f"    -> {len(entries)} entries")

            update_rss_feed_status(
                feed_id,
                status=result.status_code or (200 if result.success else 500),
                etag=result.etag,
                last_modified=result.last_modified,
            )

        except Exception as e:
            logger.error(f"    -> Error: {e}")
            update_rss_feed_status(feed_id, status=500)

    # Cleanup old entries
    retention = display.get("article_retention_days", 30)
    deleted = cleanup_old_rss_entries(days=retention)
    if deleted:
        logger.info(f"  Cleaned up {deleted} old RSS entries")
```

In `main()`, after `fetch_feeds()`:
```python
# Fetch RSS feeds
rss_config = {}
rss_config_path = CONFIG_DIR / "rss_feeds.yaml"
if rss_config_path.exists():
    with open(rss_config_path) as f:
        rss_config = yaml.safe_load(f) or {}

if not args.gen_only and rss_config.get("rss_feeds"):
    fetch_rss(rss_config)
```

**Step 2: Commit**

```bash
git add src/main.py
git commit -m "feat(rss): integrate RSS fetch into main orchestrator pipeline"
```

---

## Task 8: Dashboard RSS summary card

**Files:**
- Modify: `src/generator/html.py`
- Modify: `templates/dashboard.html`

**Step 1: Update `build_dashboard_context()` to include RSS data**

Add to the context building:
```python
# Get RSS entries for dashboard summary card
from src.storage.database import get_all_rss_entries, get_all_rss_feeds
rss_entries = get_all_rss_entries(limit=50)
rss_feeds = get_all_rss_feeds()

# Group entries by category
rss_by_category = {}
for entry in rss_entries:
    cat = entry.get("category", "other")
    rss_by_category.setdefault(cat, []).append(entry)
    # Enrich with time_ago
    entry["time_ago"] = time_ago(entry.get("published_at"))
    entry["domain"] = extract_domain(entry.get("url"))
```

Add to the returned context dict:
```python
"rss_entries": rss_entries,
"rss_by_category": rss_by_category,
"rss_feeds": rss_feeds,
```

**Step 2: Add RSS card to dashboard template**

In `templates/dashboard.html`, add RSS card handling. Add a new card type `rss_summary` to the Jinja2 template and the JavaScript rendering engine. The RSS summary card shows category names with entry counts and links to `reader.html`.

**Step 3: Commit**

```bash
git add src/generator/html.py templates/dashboard.html
git commit -m "feat(rss): add RSS summary card to dashboard"
```

---

## Task 9: Reader page — timeline with keyboard navigation

**Files:**
- Create: `templates/reader.html`
- Modify: `src/generator/html.py` (add `generate_reader()`)

**Step 1: Create reader.html Jinja2 template**

The reader page follows the same Flexoki/IBM Plex Mono theme. It displays a chronological timeline of RSS entries grouped by category with:
- Canvas-rendered entry rows (matching dashboard card style)
- Category tabs for filtering
- Keyboard navigation (j/k/o/s)
- Time-decay styling (entries fade as they age)
- Links to individual article pages (`read/<entry-id>.html`)
- "Open original" link for source URL

**Step 2: Add `generate_reader()` function to html.py**

```python
def generate_reader() -> Path:
    """Generate the RSS reader page."""
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    template = env.get_template("reader.html")

    rss_entries = get_all_rss_entries(limit=200)
    rss_feeds = get_all_rss_feeds()

    # Enrich entries
    for entry in rss_entries:
        entry["time_ago"] = time_ago(entry.get("published_at"))
        entry["domain"] = extract_domain(entry.get("url"))

    # Group by category
    by_category = {}
    for entry in rss_entries:
        cat = entry.get("category", "other")
        by_category.setdefault(cat, []).append(entry)

    context = {
        "title": "Meridian Reader",
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "entries": rss_entries,
        "by_category": by_category,
        "feeds": rss_feeds,
        "categories": sorted(by_category.keys()),
    }

    reader_json = json.dumps(context, separators=(",", ":"), ensure_ascii=False, default=str)
    reader_json = reader_json.replace("</", "<\\/")

    html = template.render(**context, reader_json=reader_json)
    output_path = OUTPUT_DIR / "reader.html"
    output_path.write_text(html, encoding="utf-8")
    return output_path
```

Wire into `generate_dashboard()` or call separately from `main()`.

**Step 3: Commit**

```bash
git add templates/reader.html src/generator/html.py
git commit -m "feat(rss): add reader.html timeline page with keyboard nav"
```

---

## Task 10: Article reader pages — pretext-rendered

**Files:**
- Create: `templates/article.html`
- Modify: `src/generator/html.py` (add `generate_article_pages()`)

**Step 1: Create article.html template**

A clean, distraction-free reading page using pretext for text layout:
- Flexoki theme, IBM Plex Mono for UI, system serif for article body
- Pretext-powered text measurement for responsive line wrapping
- Article metadata header (source, author, date, word count, reading time)
- Navigation: back to reader, previous/next article
- "Open original" link
- Falls back to summary + link if content extraction failed

Loads pretext via CDN:
```html
<script type="module">
  var _pretext = null;
  try {
    var mod = await import('https://cdn.jsdelivr.net/npm/@chenglou/pretext@0.0.3/dist/layout.js');
    _pretext = { prepare: mod.prepare, layout: mod.layout };
  } catch (e) { /* fallback to plain rendering */ }
</script>
```

**Step 2: Add `generate_article_pages()` function**

```python
def generate_article_pages() -> int:
    """Generate individual article reading pages. Returns count generated."""
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    template = env.get_template("article.html")

    entries = get_all_rss_entries(limit=200)

    article_dir = OUTPUT_DIR / "read"
    article_dir.mkdir(exist_ok=True)

    count = 0
    for i, entry in enumerate(entries):
        if not entry.get("content") and not entry.get("summary"):
            continue

        entry["time_ago"] = time_ago(entry.get("published_at"))
        prev_entry = entries[i - 1] if i > 0 else None
        next_entry = entries[i + 1] if i < len(entries) - 1 else None

        html = template.render(
            title=entry["title"],
            entry=entry,
            prev_entry=prev_entry,
            next_entry=next_entry,
            generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        )

        output_path = article_dir / f"{entry['id']}.html"
        output_path.write_text(html, encoding="utf-8")
        count += 1

    return count
```

**Step 3: Commit**

```bash
git add templates/article.html src/generator/html.py
git commit -m "feat(rss): add pretext-rendered article reading pages"
```

---

## Task 11: GitHub Actions integration

**Files:**
- Modify: `.github/workflows/update.yaml`
- Modify: `.github/workflows/update-dashboard.yml`

**Step 1: Add RSS steps to workflows**

In the workflow, after the existing fetch steps:
- The existing `python -m src.main` already runs the full pipeline (now includes `fetch_rss`)
- Add `docs/reader.html` and `docs/read/` to the git add step

```yaml
# In the commit step, add:
git add docs/index.html docs/CODEBOOK.html docs/reader.html docs/read/ || true
```

**Step 2: Commit**

```bash
git add .github/workflows/update.yaml .github/workflows/update-dashboard.yml
git commit -m "feat(rss): add RSS pages to GitHub Actions deploy"
```

---

## Task 12: End-to-end verification

**Step 1: Run full pipeline locally**

```bash
python -m src.rss list                    # verify seed feeds show
python -m src.main                        # full fetch + generate
ls docs/reader.html                       # reader page exists
ls docs/read/                             # article pages exist
```

**Step 2: Open in browser and verify**

- `docs/index.html` — RSS summary card visible in masonry grid
- `docs/reader.html` — timeline with quantum computing entries
- `docs/read/<id>.html` — article renders with pretext styling
- Keyboard nav works (j/k/o/s)
- No JS console errors

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat(rss): complete RSS reader integration — v1"
```

---

## Dependency Summary

```
Task 1 (Models)          → standalone
Task 2 (Database)        → depends on Task 1
Task 3 (RSSConnector)    → depends on Task 1
Task 4 (Extractor)       → standalone
Task 5 (Config + deps)   → standalone
Task 6 (CLI)             → depends on Tasks 2, 3
Task 7 (Orchestrator)    → depends on Tasks 2, 3, 4, 5
Task 8 (Dashboard card)  → depends on Task 2
Task 9 (Reader page)     → depends on Task 2
Task 10 (Article pages)  → depends on Task 2, 4
Task 11 (GitHub Actions) → depends on Tasks 7-10
Task 12 (E2E verify)     → depends on all
```

**Parallelizable:** Tasks 1, 4, 5 can run in parallel. Tasks 3 and 4 can run in parallel. Tasks 8, 9, 10 can run in parallel after Task 2.
