"""
Abstract base class for all data connectors.

All connectors must implement:
1. fetch() - Retrieve raw data from source
2. normalize() - Convert to standard Observation/Story format
3. health_check() - Verify API connectivity
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from ..storage.models import Observation, Story


@dataclass
class ConnectorConfig:
    """Configuration passed to connectors."""
    metric_id: str
    name: str
    source: str
    frequency: str
    unit: Optional[str] = None
    decimals: int = 2
    transform: Optional[str] = None
    multiplier: float = 1.0
    # Source-specific fields
    series_id: Optional[str] = None  # FRED
    dataflow: Optional[str] = None   # ECB
    series_key: Optional[str] = None  # ECB
    indicator: Optional[str] = None  # World Bank
    country: Optional[str] = None    # World Bank


@dataclass
class FeedConfig:
    """Configuration for tech feeds."""
    id: str
    name: str
    source: str
    limit: int = 20
    # Source-specific
    endpoint: Optional[str] = None   # HN Firebase
    query: Optional[str] = None      # HN Algolia
    tags: Optional[str] = None       # HN Algolia
    time_range: Optional[str] = None  # HN Algolia
    min_score: Optional[int] = None  # HN Algolia: minimum points filter
    sort_by: Optional[str] = None    # HN Algolia: "popularity" or "date"


@dataclass
class FetchResult:
    """Result of a fetch operation."""
    success: bool
    data: list[Any]
    error: Optional[str] = None
    source: str = ""
    fetched_at: datetime = None

    def __post_init__(self):
        if self.fetched_at is None:
            self.fetched_at = datetime.now()


class BaseMetricConnector(ABC):
    """Abstract base for metric data connectors."""

    SOURCE_NAME: str = "base"

    @abstractmethod
    def fetch(self, config: ConnectorConfig) -> FetchResult:
        """
        Fetch raw data from the source API.

        Args:
            config: Metric configuration

        Returns:
            FetchResult with raw API response data
        """
        pass

    @abstractmethod
    def normalize(self, config: ConnectorConfig, raw_data: list[Any]) -> list[Observation]:
        """
        Convert raw API data to standard Observation format.

        Args:
            config: Metric configuration
            raw_data: Raw data from fetch()

        Returns:
            List of normalized Observation objects
        """
        pass

    def health_check(self) -> bool:
        """
        Verify API connectivity.

        Returns:
            True if API is reachable and responding
        """
        return True

    def fetch_and_normalize(self, config: ConnectorConfig) -> list[Observation]:
        """
        Convenience method: fetch + normalize in one call.
        """
        result = self.fetch(config)
        if not result.success:
            raise RuntimeError(f"Fetch failed: {result.error}")
        return self.normalize(config, result.data)


class BaseFeedConnector(ABC):
    """Abstract base for tech feed connectors."""

    SOURCE_NAME: str = "base"

    @abstractmethod
    def fetch(self, config: FeedConfig) -> FetchResult:
        """Fetch stories from the feed source."""
        pass

    @abstractmethod
    def normalize(self, config: FeedConfig, raw_data: list[Any]) -> list[Story]:
        """Convert raw data to Story objects."""
        pass

    def fetch_and_normalize(self, config: FeedConfig) -> list[Story]:
        """Convenience method: fetch + normalize."""
        result = self.fetch(config)
        if not result.success:
            raise RuntimeError(f"Fetch failed: {result.error}")
        return self.normalize(config, result.data)
