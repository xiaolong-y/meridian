"""RSS/Atom feed connector using feedparser."""
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from time import mktime
from typing import Any, Optional

import feedparser
import requests

from src.connectors.base import FetchResult
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
    etag: Optional[str] = None
    last_modified: Optional[str] = None


def make_entry_id(feed_id: str, guid: str) -> str:
    """Generate a stable entry ID from feed_id + guid."""
    raw = f"{feed_id}:{guid}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class RSSConnector:
    """RSS/Atom feed connector with conditional GET."""

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
                    success=True, data=[], source=self.SOURCE_NAME,
                    status_code=304,
                )

            resp.raise_for_status()
            feed = feedparser.parse(resp.content)

            return FetchResult(
                success=True,
                data=feed.entries[:config.limit],
                source=self.SOURCE_NAME,
                etag=resp.headers.get("ETag"),
                last_modified=resp.headers.get("Last-Modified"),
                status_code=resp.status_code,
            )

        except requests.RequestException as e:
            logger.error(f"  {config.id}: fetch failed — {e}")
            return FetchResult(
                success=False, data=[], error=str(e),
                source=self.SOURCE_NAME,
            )

    def normalize(self, config: RSSFeedConfig, raw_data: list[Any]) -> list[RSSEntry]:
        """Convert feedparser entries to RSSEntry objects."""
        entries = []

        for item in raw_data:
            guid = item.get("id") or item.get("link") or item.get("title", "")
            entry_id = make_entry_id(config.id, guid)

            # Parse published date
            published_at = None
            for date_field in ("published_parsed", "updated_parsed"):
                parsed = item.get(date_field)
                if parsed:
                    try:
                        published_at = datetime.fromtimestamp(mktime(parsed))
                        break
                    except (ValueError, OverflowError, TypeError):
                        continue

            # Extract summary text
            summary = ""
            if item.get("content"):
                summary = item.content[0].get("value", "")
            elif item.get("summary"):
                summary = item.summary
            if summary:
                summary = re.sub(r"<[^>]+>", "", summary)
                summary = re.sub(r"\s+", " ", summary).strip()[:500]

            word_count = len(summary.split()) if summary else None
            read_time = (word_count // 200) + 1 if word_count else None

            entries.append(RSSEntry(
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
                content_hash=hashlib.md5(summary.encode()).hexdigest() if summary else None,
            ))

        return entries

    def fetch_and_normalize(self, config: RSSFeedConfig) -> list[RSSEntry]:
        """Convenience: fetch + normalize."""
        result = self.fetch(config)
        if not result.success:
            raise RuntimeError(f"Fetch failed: {result.error}")
        return self.normalize(config, result.data), result
