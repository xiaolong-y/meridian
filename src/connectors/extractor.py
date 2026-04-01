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
