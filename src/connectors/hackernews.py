"""
Hacker News connectors (Firebase official API + Algolia search).

Firebase API:
- Official HN API
- Real-time item data
- Top/best/new story lists
- No rate limit (be polite)

Algolia API:
- Full-text search
- Filtering by date, tags
- Faster for bulk retrieval
"""
from datetime import datetime
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .base import BaseFeedConnector, FeedConfig, FetchResult
from ..storage.models import Story


class HNFirebaseConnector(BaseFeedConnector):
    """Connector for official HN Firebase API."""

    SOURCE_NAME = "hn_firebase"
    BASE_URL = "https://hacker-news.firebaseio.com/v0"

    def fetch(self, config: FeedConfig) -> FetchResult:
        """
        Fetch stories from HN Firebase.

        Args:
            config: Must include endpoint (topstories, beststories, newstories)

        Returns:
            FetchResult with story items
        """
        endpoint = config.endpoint or "topstories"
        limit = config.limit or 20

        try:
            # Get story IDs
            ids_url = f"{self.BASE_URL}/{endpoint}.json"
            response = requests.get(ids_url, timeout=15)
            response.raise_for_status()
            story_ids = response.json()[:limit]

            # Fetch individual stories in parallel
            stories = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {
                    executor.submit(self._fetch_item, sid): sid
                    for sid in story_ids
                }
                for future in as_completed(futures):
                    try:
                        item = future.result()
                        if item and item.get("type") == "story":
                            stories.append(item)
                    except Exception:
                        continue

            return FetchResult(
                success=True,
                data=stories,
                source=self.SOURCE_NAME
            )

        except requests.RequestException as e:
            return FetchResult(
                success=False,
                data=[],
                error=str(e),
                source=self.SOURCE_NAME
            )

    def _fetch_item(self, item_id: int) -> dict | None:
        """Fetch a single HN item."""
        try:
            response = requests.get(
                f"{self.BASE_URL}/item/{item_id}.json",
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

    def normalize(self, config: FeedConfig, raw_data: list[Any]) -> list[Story]:
        """Convert HN items to Story objects."""
        stories = []

        for item in raw_data:
            if not item:
                continue

            # Parse Unix timestamp
            posted_at = None
            if item.get("time"):
                posted_at = datetime.fromtimestamp(item["time"])

            story = Story(
                id=item["id"],
                title=item.get("title", ""),
                url=item.get("url"),
                score=item.get("score", 0),
                comments=item.get("descendants", 0),
                author=item.get("by", ""),
                posted_at=posted_at,
                source=self.SOURCE_NAME,
                feed_id=config.id,
                retrieved_at=datetime.now()
            )
            stories.append(story)

        return stories


class HNAlgoliaConnector(BaseFeedConnector):
    """Connector for HN Algolia Search API."""

    SOURCE_NAME = "hn_algolia"
    BASE_URL = "https://hn.algolia.com/api/v1"

    def fetch(self, config: FeedConfig) -> FetchResult:
        """
        Search HN via Algolia.

        Args:
            config: Should include query, optional tags, time_range

        Returns:
            FetchResult with search hits
        """
        if not config.query:
            return FetchResult(
                success=False,
                data=[],
                error="query required for Algolia search",
                source=self.SOURCE_NAME
            )

        params = {
            "query": config.query,
            "hitsPerPage": config.limit or 20,
        }

        # Add tags filter (story, comment, etc.)
        if config.tags:
            params["tags"] = config.tags

        # Add time filter
        if config.time_range:
            import time
            now = int(time.time())
            ranges = {
                "day": 86400,
                "week": 604800,
                "month": 2592000,
                "year": 31536000,
            }
            if config.time_range in ranges:
                params["numericFilters"] = f"created_at_i>{now - ranges[config.time_range]}"

        try:
            # Use search_by_date for recent content
            url = f"{self.BASE_URL}/search_by_date" if config.time_range else f"{self.BASE_URL}/search"
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            return FetchResult(
                success=True,
                data=data.get("hits", []),
                source=self.SOURCE_NAME
            )

        except requests.RequestException as e:
            return FetchResult(
                success=False,
                data=[],
                error=str(e),
                source=self.SOURCE_NAME
            )

    def normalize(self, config: FeedConfig, raw_data: list[Any]) -> list[Story]:
        """Convert Algolia hits to Story objects."""
        stories = []

        for hit in raw_data:
            # Parse ISO timestamp
            posted_at = None
            if hit.get("created_at"):
                try:
                    posted_at = datetime.fromisoformat(
                        hit["created_at"].replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            story = Story(
                id=int(hit.get("objectID", 0)),
                title=hit.get("title", ""),
                url=hit.get("url"),
                score=hit.get("points", 0),
                comments=hit.get("num_comments", 0),
                author=hit.get("author", ""),
                posted_at=posted_at,
                source=self.SOURCE_NAME,
                feed_id=config.id,
                retrieved_at=datetime.now()
            )
            stories.append(story)

        return stories
