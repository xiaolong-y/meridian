"""
Static HTML dashboard generator.

Generates a single-page dense dashboard using Jinja2 templates.
Output is a self-contained HTML file suitable for GitHub Pages.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import yaml
from jinja2 import Environment, FileSystemLoader

from ..storage.database import get_all_metric_meta, get_stories_by_feed, get_latest_observations
from ..transforms.calculations import prepare_sparkline_data, generate_ascii_sparkline, generate_braille_sparkline

# Symbol mappings for enhanced visual display
SECTION_ICONS = {
    "US Economy": "🇺🇸",
    "Eurozone": "🇪🇺",
    "Asia Pacific": "🌏",
    "Global Markets": "🌐",
    "Crypto": "₿",
    "Tech Discussion": "💻",
    "AI/ML": "🤖",
    "Infrastructure": "🏗",
    "Markets & Finance": "📊",
    "China Tech": "🇨🇳",
    "Top Stories": "📰",
}

ASSET_ICONS = {
    "Bitcoin": "₿",
    "Ethereum": "Ξ",
    "Brent Crude": "🛢",
    "Gold": "🥇",
    "USD Trade Weighted": "💵",
}


def get_directional_arrow(change: Optional[float]) -> str:
    """Return directional arrow based on change value."""
    if change is None:
        return ""
    if change > 0:
        return "⬆"
    elif change < 0:
        return "⬇"
    return "→"


def get_heat_symbol(score: int) -> str:
    """Return heat indicator based on score threshold."""
    if score >= 1000:
        return "🔥"  # viral
    elif score >= 500:
        return "⚡"  # hot
    elif score >= 200:
        return "✦"  # notable
    return "•"  # standard


def get_time_symbol(time_str: str) -> str:
    """Return time symbol based on age."""
    if not time_str:
        return ""

    # Parse the time_ago string
    if time_str == "now" or time_str.endswith("m"):
        return "⚡"  # just posted (<1h)
    elif time_str.endswith("h"):
        hours = int(time_str[:-1]) if time_str[:-1].isdigit() else 0
        if hours <= 6:
            return "⏱"  # recent (1-6h)
        else:
            return "🕐"  # today (6-24h)
    elif time_str.endswith("d"):
        return "📅"  # days old
    elif time_str.endswith("w"):
        return "📆"  # week+
    return ""


def get_section_icon(name: str) -> str:
    """Get icon for section header."""
    return SECTION_ICONS.get(name, "")


def extract_domain(url: Optional[str]) -> str:
    """Extract domain from URL for display."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        return domain
    except Exception:
        return ""


def time_ago(posted_at: Optional[str]) -> str:
    """Convert timestamp to human-readable time ago."""
    if not posted_at:
        return ""
    try:
        if isinstance(posted_at, str):
            # Handle ISO format
            posted_at = posted_at.replace("Z", "+00:00")
            dt = datetime.fromisoformat(posted_at)
        else:
            dt = posted_at

        # Make comparison timezone-naive
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)

        now = datetime.utcnow()
        diff = now - dt

        seconds = diff.total_seconds()
        if seconds < 60:
            return "now"
        elif seconds < 3600:
            mins = int(seconds / 60)
            return f"{mins}m"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours}h"
        elif seconds < 604800:
            days = int(seconds / 86400)
            return f"{days}d"
        else:
            weeks = int(seconds / 604800)
            return f"{weeks}w"
    except Exception:
        return ""

TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "docs"
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def load_config() -> dict:
    """
    Load metric and feed configurations from YAML files.

    Returns:
        Dictionary containing 'metrics' and 'feeds' configurations
    """
    with open(CONFIG_DIR / "metrics.yaml") as f:
        metrics_config = yaml.safe_load(f)

    with open(CONFIG_DIR / "feeds.yaml") as f:
        feeds_config = yaml.safe_load(f)

    return {
        "metrics": metrics_config,
        "feeds": feeds_config
    }


def format_value(value: Optional[float], unit: Optional[str]) -> str:
    """
    Format a metric value with its unit.

    Args:
        value: The numeric value to format
        unit: The unit string (%, bp, $/bbl, etc.)

    Returns:
        Formatted string representation
    """
    if value is None:
        return "—"

    if unit == "%":
        return f"{value:.1f}%"
    elif unit == "bp":
        return f"{value:.0f}bp"
    elif unit and "$" in unit:
        return f"${value:,.2f}"
    elif unit == "index":
        return f"{value:.1f}"
    else:
        return f"{value:,.2f}"


def format_change(change: Optional[float], unit: Optional[str]) -> str:
    """
    Format a change value with appropriate prefix.

    Args:
        change: The change value
        unit: The unit string

    Returns:
        Formatted string with +/- prefix
    """
    if change is None:
        return ""

    prefix = "+" if change > 0 else ""

    if unit == "%":
        return f"{prefix}{change:.2f}pp"
    elif unit == "bp":
        return f"{prefix}{change:.0f}bp"
    else:
        return f"{prefix}{change:.2f}"


def get_change_period(metric_config: dict) -> str:
    """
    Determine the change period label for a metric.

    Uses explicit change_period if set, otherwise derives from frequency.

    Args:
        metric_config: Metric configuration dict from YAML

    Returns:
        Period label: DoD, MoM, QoQ, or YoY
    """
    # Use explicit change_period if specified
    if metric_config.get("change_period"):
        return metric_config["change_period"]

    # Derive from frequency
    frequency = metric_config.get("frequency", "monthly")
    period_map = {
        "daily": "DoD",
        "monthly": "MoM",
        "quarterly": "QoQ",
        "annual": "YoY",
    }
    return period_map.get(frequency, "")


def build_dashboard_context() -> dict[str, Any]:
    """
    Build template context from database.

    Queries the database for metric metadata and stories,
    generates sparklines, and formats values for display.

    Returns:
        Dictionary with all data needed for dashboard template
    """
    config = load_config()

    # Get all metric metadata from database
    all_meta = get_all_metric_meta()
    meta_lookup = {m["id"]: m for m in all_meta}

    # Build lookup for metric configs by ID
    metric_config_lookup = {m["id"]: m for m in config["metrics"].get("metrics", [])}

    # Build metric groups with sparklines
    metric_groups = []
    for group in config["metrics"].get("groups", []):
        group_metrics = []
        for metric_id in group.get("metrics", []):
            meta = meta_lookup.get(metric_id)

            if meta:
                # Generate sparkline from recent observations using braille patterns
                observations = get_latest_observations(metric_id, limit=20)
                sparkline_values = prepare_sparkline_data(observations, points=16)
                sparkline = generate_braille_sparkline(sparkline_values, width=8)

                # Determine change direction for styling
                change_class = ""
                if meta.get("change") is not None:
                    if meta["change"] > 0:
                        change_class = "up"
                    elif meta["change"] < 0:
                        change_class = "down"

                # Get change period label from config
                metric_cfg = metric_config_lookup.get(metric_id, {})
                change_period = get_change_period(metric_cfg)

                group_metrics.append({
                    **meta,
                    "sparkline": sparkline,
                    "sparkline_values": sparkline_values,
                    "change_class": change_class,
                    "change_period": change_period,
                    "direction_arrow": get_directional_arrow(meta.get("change")),
                    "formatted_value": format_value(meta.get("last_value"), meta.get("unit")),
                    "formatted_change": format_change(meta.get("change"), meta.get("unit")),
                })
            else:
                # Metric not in database yet - show placeholder
                group_metrics.append({
                    "id": metric_id,
                    "name": metric_id,
                    "sparkline": "",
                    "sparkline_values": [],
                    "change_class": "",
                    "change_period": "",
                    "formatted_value": "—",
                    "formatted_change": "",
                })

        metric_groups.append({
            "name": group["name"],
            "metrics": group_metrics
        })

    # Get stories organized by feed, with domain and time_ago
    feeds = []
    for feed_config in config["feeds"].get("feeds", []):
        stories = get_stories_by_feed(feed_config["id"], limit=feed_config.get("limit", 20))
        # Enrich stories with domain, time_ago, and symbols
        for story in stories:
            story["domain"] = extract_domain(story.get("url"))
            story["time_ago"] = time_ago(story.get("posted_at"))
            story["heat_symbol"] = get_heat_symbol(story.get("score", 0))
            story["time_symbol"] = get_time_symbol(story["time_ago"])
        feeds.append({
            "id": feed_config["id"],
            "name": feed_config["name"],
            "stories": stories
        })

    # Build interleaved card order: distribute feeds evenly among metric groups
    card_order = []
    feed_ids = [f["id"] for f in feeds]
    n_metrics = len(metric_groups)
    n_feeds = len(feed_ids)
    if n_feeds > 0 and n_metrics > 0:
        step = n_metrics / n_feeds
        feed_positions = {int((i + 0.5) * step) for i in range(n_feeds)}
    else:
        feed_positions = set()

    feed_idx = 0
    for i in range(n_metrics):
        card_order.append({"type": "metric", "index": i})
        if i in feed_positions and feed_idx < n_feeds:
            card_order.append({"type": "feed", "id": feed_ids[feed_idx]})
            feed_idx += 1
    while feed_idx < n_feeds:
        card_order.append({"type": "feed", "id": feed_ids[feed_idx]})
        feed_idx += 1

    return {
        "title": "Meridian",
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "metric_groups": metric_groups,
        "feeds": feeds,
        "card_order": card_order,
    }


def generate_dashboard() -> Path:
    """
    Generate the static HTML dashboard.

    Loads the Jinja2 template, builds context from database,
    serializes data as JSON for canvas rendering, and writes to docs/index.html.

    Returns:
        Path to generated index.html
    """
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=True
    )

    template = env.get_template("dashboard.html")
    context = build_dashboard_context()

    # Serialize context to JSON for client-side canvas rendering
    # Sanitize to prevent </script> injection in story titles
    dashboard_json = json.dumps(context, separators=(",", ":"), ensure_ascii=False)
    dashboard_json = dashboard_json.replace("</", "<\\/")
    dashboard_json = dashboard_json.replace("\u2028", "\\u2028")
    dashboard_json = dashboard_json.replace("\u2029", "\\u2029")

    html = template.render(**context, dashboard_json=dashboard_json)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "index.html"
    output_path.write_text(html, encoding="utf-8")

    return output_path


if __name__ == "__main__":
    path = generate_dashboard()
    print(f"Generated: {path}")
