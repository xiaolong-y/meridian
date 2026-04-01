"""
SQLite database operations for Meridian.

Design principles:
- Append-only for observations (full history)
- Rolling window for stories (7 days)
- Idempotent upserts (safe to re-run)
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generator

from .models import Observation, Story, MetricMeta, RSSFeed, RSSEntry

DB_PATH = Path(__file__).parent.parent.parent / "data" / "meridian.db"

SCHEMA = """
-- Macro observations (append-only, keeps full history)
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_id TEXT NOT NULL,
    obs_date TEXT NOT NULL,  -- YYYY-MM-DD
    value REAL NOT NULL,
    unit TEXT,
    source TEXT NOT NULL,
    retrieved_at TEXT DEFAULT (datetime('now')),
    UNIQUE(metric_id, obs_date, source)
);

CREATE INDEX IF NOT EXISTS idx_obs_metric ON observations(metric_id);
CREATE INDEX IF NOT EXISTS idx_obs_date ON observations(obs_date DESC);

-- Tech stories (rolling 7-day window)
CREATE TABLE IF NOT EXISTS stories (
    id INTEGER NOT NULL,  -- HN item ID
    title TEXT NOT NULL,
    url TEXT,
    score INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    author TEXT,
    posted_at TEXT,
    source TEXT NOT NULL,
    feed_id TEXT NOT NULL,
    retrieved_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (id, feed_id)
);

CREATE INDEX IF NOT EXISTS idx_stories_feed ON stories(feed_id);
CREATE INDEX IF NOT EXISTS idx_stories_score ON stories(score DESC);

-- RSS feed subscriptions
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
);

-- RSS feed entries
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
);

CREATE INDEX IF NOT EXISTS idx_rss_entries_feed ON rss_entries(feed_id);
CREATE INDEX IF NOT EXISTS idx_rss_entries_published ON rss_entries(published_at DESC);

-- Saved RSS entries (read-later)
CREATE TABLE IF NOT EXISTS rss_saved (
    entry_id TEXT PRIMARY KEY,
    saved_at TEXT DEFAULT (datetime('now')),
    note TEXT
);

-- Metric metadata cache
CREATE TABLE IF NOT EXISTS metrics (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    frequency TEXT,
    unit TEXT,
    last_value REAL,
    last_updated TEXT,
    previous_value REAL,
    change REAL,
    change_percent REAL
);
"""


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for database connections."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Initialize database schema."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)


def upsert_observation(obs: Observation) -> None:
    """Insert or update an observation."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO observations (metric_id, obs_date, value, unit, source)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(metric_id, obs_date, source)
            DO UPDATE SET value = excluded.value, retrieved_at = datetime('now')
        """, (obs.metric_id, obs.obs_date, obs.value, obs.unit, obs.source))


def upsert_story(story: Story) -> None:
    """Insert or update a story."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO stories (id, title, url, score, comments, author, posted_at, source, feed_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id, feed_id) DO UPDATE SET
                score = excluded.score,
                comments = excluded.comments,
                retrieved_at = datetime('now')
        """, (story.id, story.title, story.url, story.score, story.comments,
              story.author, story.posted_at.isoformat() if story.posted_at else None,
              story.source, story.feed_id))


def get_latest_observations(metric_id: str, limit: int = 120) -> list[dict]:
    """Get recent observations for a metric."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT obs_date, value, unit, source, retrieved_at
            FROM observations
            WHERE metric_id = ?
            ORDER BY obs_date DESC
            LIMIT ?
        """, (metric_id, limit)).fetchall()
        return [dict(row) for row in rows]


def get_stories_by_feed(feed_id: str, limit: int = 20) -> list[dict]:
    """Get stories for a specific feed."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT id, title, url, score, comments, author, posted_at, source
            FROM stories
            WHERE feed_id = ?
            ORDER BY score DESC
            LIMIT ?
        """, (feed_id, limit)).fetchall()
        return [dict(row) for row in rows]


def cleanup_old_stories(days: int = 7) -> int:
    """Remove stories older than N days. Returns count deleted."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM stories WHERE retrieved_at < ?", (cutoff,)
        )
        return cursor.rowcount


def clear_feed_stories(feed_id: str) -> int:
    """Clear all stories for a feed before refresh. Returns count deleted."""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM stories WHERE feed_id = ?", (feed_id,)
        )
        return cursor.rowcount


def update_metric_meta(meta: MetricMeta) -> None:
    """Update metric metadata cache."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO metrics (id, name, source, frequency, unit,
                                 last_value, last_updated, previous_value, change, change_percent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                last_value = excluded.last_value,
                last_updated = excluded.last_updated,
                previous_value = excluded.previous_value,
                change = excluded.change,
                change_percent = excluded.change_percent
        """, (meta.id, meta.name, meta.source, meta.frequency, meta.unit,
              meta.last_value, meta.last_updated.isoformat() if meta.last_updated else None,
              meta.previous_value, meta.change, meta.change_percent))


def get_all_metric_meta() -> list[dict]:
    """Get all metric metadata for dashboard display."""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM metrics ORDER BY id").fetchall()
        return [dict(row) for row in rows]


# ── RSS feed operations ──────────────────────────────────────────────


def upsert_rss_feed(feed: RSSFeed) -> None:
    """Insert or update an RSS feed subscription."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO rss_feeds (id, title, feed_url, site_url, category, tier, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title, feed_url=excluded.feed_url,
                site_url=excluded.site_url, category=excluded.category,
                tier=excluded.tier
        """, (feed.id, feed.title, feed.feed_url, feed.site_url,
              feed.category, feed.tier))


def update_rss_feed_status(feed_id: str, status: int,
                           etag: str = None, last_modified: str = None) -> None:
    """Update feed polling status after fetch."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE rss_feeds SET
                last_status = ?, etag = COALESCE(?, etag),
                last_modified = COALESCE(?, last_modified),
                last_fetched_at = datetime('now'),
                error_count = CASE WHEN ? < 400 THEN 0 ELSE error_count + 1 END
            WHERE id = ?
        """, (status, etag, last_modified, status, feed_id))


def upsert_rss_entry(entry: RSSEntry) -> None:
    """Insert or update an RSS entry."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO rss_entries
                (id, feed_id, guid, title, url, summary, content,
                 content_hash, author, published_at, fetched_at,
                 word_count, read_time_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title, summary=excluded.summary,
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
            SELECT * FROM rss_entries WHERE feed_id = ?
            ORDER BY published_at DESC LIMIT ?
        """, (feed_id, limit)).fetchall()
        return [dict(r) for r in rows]


def get_all_rss_entries(limit: int = 100) -> list[dict]:
    """Get all RSS entries with feed metadata for reader page."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT e.*, f.title as feed_title, f.category, f.tier, f.site_url
            FROM rss_entries e JOIN rss_feeds f ON e.feed_id = f.id
            ORDER BY e.published_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_all_rss_feeds() -> list[dict]:
    """Get all RSS feed subscriptions."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM rss_feeds ORDER BY category, title"
        ).fetchall()
        return [dict(r) for r in rows]


def get_rss_entry(entry_id: str) -> dict:
    """Get a single RSS entry by ID."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT e.*, f.title as feed_title, f.category, f.tier, f.site_url
            FROM rss_entries e JOIN rss_feeds f ON e.feed_id = f.id
            WHERE e.id = ?
        """, (entry_id,)).fetchone()
        return dict(row) if row else None


def cleanup_old_rss_entries(days: int = 30) -> int:
    """Remove RSS entries older than N days (except saved). Returns count."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        cursor = conn.execute("""
            DELETE FROM rss_entries
            WHERE fetched_at < ?
            AND id NOT IN (SELECT entry_id FROM rss_saved)
        """, (cutoff,))
        return cursor.rowcount
