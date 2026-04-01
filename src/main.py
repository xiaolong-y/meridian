"""
Bloomberg-Lite main orchestrator.

Coordinates:
1. Loading configuration
2. Fetching data from all sources
3. Storing observations
4. Generating dashboard

Usage:
    python -m src.main              # Full update
    python -m src.main --fetch-only # Fetch data only
    python -m src.main --gen-only   # Generate dashboard only
"""
import argparse
import logging
from datetime import datetime
from pathlib import Path

import yaml

from .connectors import (
    FREDConnector,
    ECBConnector,
    WorldBankConnector,
    IMFConnector,
    EStatDashboardConnector,
    CoinGeckoConnector,
    YahooFinanceConnector,
    OECDConnector,
    DBnomicsConnector,
    HuggingFaceConnector,
    VastAIConnector,
    HNFirebaseConnector,
    HNAlgoliaConnector,
    ConnectorConfig,
    FeedConfig,
)
from .storage.database import (
    init_db,
    upsert_observation,
    upsert_story,
    update_metric_meta,
    cleanup_old_stories,
    clear_feed_stories,
    upsert_rss_feed,
    upsert_rss_entry,
    update_rss_feed_status,
    cleanup_old_rss_entries,
    get_all_rss_feeds,
)
from .storage.models import MetricMeta, RSSFeed
from .connectors.rss import RSSConnector, RSSFeedConfig
from .connectors.extractor import extract_article
from .transforms.calculations import (
    calculate_change,
    calculate_yoy_percent,
    calculate_qoq_percent,
)
from .generator.html import generate_dashboard, generate_reader, generate_article_pages

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"


def load_configs() -> tuple[dict, dict]:
    """
    Load metric and feed configurations from YAML files.

    Returns:
        Tuple of (metrics_config, feeds_config) dictionaries
    """
    with open(CONFIG_DIR / "metrics.yaml") as f:
        metrics = yaml.safe_load(f)
    with open(CONFIG_DIR / "feeds.yaml") as f:
        feeds = yaml.safe_load(f)
    return metrics, feeds


def fetch_metrics(metrics_config: dict) -> None:
    """
    Fetch all configured metrics from their respective sources.

    Initializes connectors for each source type and fetches data
    for all configured metrics. Results are stored in the database.

    Args:
        metrics_config: Parsed metrics.yaml configuration
    """
    # Initialize connectors (lazy - only create when needed)
    connectors = {}

    def get_connector(source: str):
        if source not in connectors:
            try:
                if source == "fred":
                    connectors[source] = FREDConnector()
                elif source == "ecb":
                    connectors[source] = ECBConnector()
                elif source == "worldbank":
                    connectors[source] = WorldBankConnector()
                elif source == "imf":
                    connectors[source] = IMFConnector()
                elif source == "estat_dashboard":
                    connectors[source] = EStatDashboardConnector()
                elif source == "coingecko":
                    connectors[source] = CoinGeckoConnector()
                elif source == "yahoo":
                    connectors[source] = YahooFinanceConnector()
                elif source == "oecd":
                    connectors[source] = OECDConnector()
                elif source == "dbnomics":
                    connectors[source] = DBnomicsConnector()
                elif source == "huggingface":
                    connectors[source] = HuggingFaceConnector()
                elif source == "vastai":
                    connectors[source] = VastAIConnector()
                else:
                    return None
            except ValueError as e:
                logger.warning(f"Skipping {source}: {e}")
                connectors[source] = None
        return connectors.get(source)

    for metric in metrics_config.get("metrics", []):
        source = metric.get("source")
        connector = get_connector(source)

        if connector is None:
            logger.warning(f"Unknown source '{source}' for metric {metric['id']}")
            continue

        config = ConnectorConfig(
            metric_id=metric["id"],
            name=metric["name"],
            source=source,
            frequency=metric.get("frequency", "monthly"),
            unit=metric.get("unit"),
            decimals=metric.get("decimals", 2),
            transform=metric.get("transform"),
            multiplier=metric.get("multiplier", 1.0),
            series_id=metric.get("series_id"),
            dataflow=metric.get("dataflow"),
            series_key=metric.get("series_key"),
            indicator=metric.get("indicator"),
            country=metric.get("country"),
            indicator_code=metric.get("indicator_code"),
        )

        logger.info(f"Fetching {config.metric_id}...")

        try:
            observations = connector.fetch_and_normalize(config)

            # Apply transforms if specified
            if config.transform and observations:
                logger.info(f"  Applying transform: {config.transform}")

                if config.transform == "yoy_percent":
                    transformed = calculate_yoy_percent(observations)
                    if transformed:
                        logger.info(f"  YoY: {len(observations)} raw -> {len(transformed)} transformed")
                        observations = transformed
                    else:
                        logger.warning(f"  YoY transform returned empty (need 13+ months)")

                elif config.transform == "qoq_percent":
                    transformed = calculate_qoq_percent(observations)
                    if transformed:
                        logger.info(f"  QoQ: {len(observations)} raw -> {len(transformed)} transformed")
                        observations = transformed
                    else:
                        logger.warning(f"  QoQ transform returned empty (need 5+ quarters)")

            # Store observations
            for obs in observations:
                upsert_observation(obs)

            # Update metric metadata with latest values
            if observations:
                latest = observations[0]
                previous = observations[1] if len(observations) > 1 else None

                change, change_pct = calculate_change(
                    latest.value,
                    previous.value if previous else None
                )

                meta = MetricMeta(
                    id=config.metric_id,
                    name=config.name,
                    source=config.source,
                    frequency=config.frequency,
                    unit=config.unit,
                    last_value=latest.value,
                    last_updated=datetime.now(),
                    previous_value=previous.value if previous else None,
                    change=change,
                    change_percent=change_pct,
                )
                update_metric_meta(meta)

            logger.info(f"  -> {len(observations)} observations stored")

        except Exception as e:
            logger.error(f"  -> Failed: {e}")


def fetch_feeds(feeds_config: dict) -> None:
    """
    Fetch all configured feeds from Hacker News sources.

    Initializes HN connectors and fetches stories for all
    configured feeds. Results are stored in the database.

    Args:
        feeds_config: Parsed feeds.yaml configuration
    """
    # Initialize connectors
    connectors = {
        "hn_firebase": HNFirebaseConnector(),
        "hn_algolia": HNAlgoliaConnector(),
    }

    for feed in feeds_config.get("feeds", []):
        source = feed.get("source")
        connector = connectors.get(source)

        if connector is None:
            logger.warning(f"Unknown source '{source}' for feed {feed['id']}")
            continue

        config = FeedConfig(
            id=feed["id"],
            name=feed["name"],
            source=source,
            limit=feed.get("limit", 20),
            endpoint=feed.get("endpoint"),
            query=feed.get("query"),
            tags=feed.get("tags"),
            time_range=feed.get("time_range"),
            min_score=feed.get("min_score"),
            sort_by=feed.get("sort_by"),
        )

        logger.info(f"Fetching feed {config.id}...")

        try:
            stories = connector.fetch_and_normalize(config)

            # Clear old stories for this feed before inserting fresh ones
            clear_feed_stories(config.id)

            # Store stories
            for story in stories:
                upsert_story(story)

            logger.info(f"  -> {len(stories)} stories stored")

        except Exception as e:
            logger.error(f"  -> Failed: {e}")


def fetch_rss(rss_config: dict) -> None:
    """Fetch all configured RSS feeds."""
    connector = RSSConnector()
    feeds = rss_config.get("rss_feeds", [])
    display = rss_config.get("display", {})

    logger.info(f"Processing {len(feeds)} RSS feeds...")

    for feed_def in feeds:
        feed_id = feed_def["id"]
        logger.info(f"  {feed_id}...")

        # Upsert feed record
        feed = RSSFeed(
            id=feed_id, title=feed_def["title"],
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
            id=feed_id, title=feed_def["title"],
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
                etag=result.etag, last_modified=result.last_modified,
            )

        except Exception as e:
            logger.error(f"    -> Error: {e}")
            update_rss_feed_status(feed_id, status=500)

    retention = display.get("article_retention_days", 30)
    deleted = cleanup_old_rss_entries(days=retention)
    if deleted:
        logger.info(f"  Cleaned up {deleted} old RSS entries")


def main():
    """Main entry point for the orchestrator."""
    parser = argparse.ArgumentParser(
        description="Bloomberg-Lite dashboard updater",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main              # Full update (fetch + generate)
  python -m src.main --fetch-only # Only fetch data, don't generate
  python -m src.main --gen-only   # Only generate dashboard from existing data
        """
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Only fetch data, don't generate dashboard"
    )
    parser.add_argument(
        "--gen-only",
        action="store_true",
        help="Only generate dashboard from existing data"
    )
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("Bloomberg-Lite Update")
    logger.info("=" * 50)

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Load configurations
    metrics_config, feeds_config = load_configs()
    logger.info(f"Loaded {len(metrics_config.get('metrics', []))} metrics, "
                f"{len(feeds_config.get('feeds', []))} feeds")

    if not args.gen_only:
        # Fetch metrics
        logger.info("")
        logger.info("Fetching metrics...")
        logger.info("-" * 30)
        fetch_metrics(metrics_config)

        # Fetch feeds
        logger.info("")
        logger.info("Fetching feeds...")
        logger.info("-" * 30)
        fetch_feeds(feeds_config)

        # Cleanup old stories
        deleted = cleanup_old_stories(days=7)
        if deleted:
            logger.info(f"Cleaned up {deleted} old stories")

        # Fetch RSS feeds
        rss_config_path = CONFIG_DIR / "rss_feeds.yaml"
        if rss_config_path.exists():
            with open(rss_config_path) as f:
                rss_config = yaml.safe_load(f) or {}
            if rss_config.get("rss_feeds"):
                logger.info("")
                logger.info("Fetching RSS feeds...")
                logger.info("-" * 30)
                fetch_rss(rss_config)

    if not args.fetch_only:
        # Generate dashboard
        logger.info("")
        logger.info("Generating dashboard...")
        logger.info("-" * 30)
        output = generate_dashboard()
        logger.info(f"Generated: {output}")

        reader = generate_reader()
        logger.info(f"Generated: {reader}")

        article_count = generate_article_pages()
        logger.info(f"Generated {article_count} article pages")

    logger.info("")
    logger.info("=" * 50)
    logger.info("Done!")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
