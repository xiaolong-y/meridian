"""
SQLite database operations for Bloomberg-Lite.

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

from .models import Observation, Story, MetricMeta

DB_PATH = Path(__file__).parent.parent.parent / "data" / "bloomberg_lite.db"

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
    id INTEGER PRIMARY KEY,  -- HN item ID
    title TEXT NOT NULL,
    url TEXT,
    score INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    author TEXT,
    posted_at TEXT,
    source TEXT NOT NULL,
    feed_id TEXT NOT NULL,
    retrieved_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_stories_feed ON stories(feed_id);
CREATE INDEX IF NOT EXISTS idx_stories_score ON stories(score DESC);

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
            ON CONFLICT(id) DO UPDATE SET
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
