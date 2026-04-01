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
    """Save RSS feeds config atomically."""
    tmp = str(CONFIG_PATH) + f".tmp.{id(config)}"
    with open(tmp, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    import os
    os.replace(tmp, CONFIG_PATH)


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
    try:
        from src.storage.database import init_db
        from src.main import fetch_rss
    except ImportError as e:
        print(f"Error: fetch_rss not yet available — {e}", file=sys.stderr)
        print("  (Task 7 wires fetch_rss into src/main.py)", file=sys.stderr)
        sys.exit(1)
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
