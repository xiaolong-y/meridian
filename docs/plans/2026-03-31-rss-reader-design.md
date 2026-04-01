# Meridian RSS: River of Curated Feeds

**Date**: 2026-03-31
**Status**: Approved

## Problem

Meridian tracks macro data and HN stories, but lacks RSS — the most important channel for curated, algorithm-free information intake. The user wants to manually pick feeds, gradually enrich their subscription list, and read articles in a clean, lightweight reader built into Meridian.

## Design Principles

1. **River, not inbox** — No unread counts. No mark-all-read. Content flows past; you catch what interests you.
2. **Curation over discovery** — Adding feeds is deliberate. Friction is a feature.
3. **Static over dynamic** — Generate at build time. Works offline, on a phone, on a Kindle.
4. **Transparent plumbing** — Show feed health, last fetch time, error status.
5. **Data portability** — OPML import/export. SQLite IS the backup.
6. **Additive to existing** — Same DB, same connector pattern, same pipeline, same theme.

## Architecture

### Data Flow

```
config/rss_feeds.yaml            <- source of truth (CLI modifies this)
        |
src/connectors/rss.py            <- RSSConnector (feedparser + conditional GET)
        |
[fetch article content]          <- trafilatura extracts text + images
        |
meridian.db                      <- rss_feeds, rss_entries, rss_saved tables
        |
src/generator/html.py            <- builds context for all pages
        |
docs/index.html                  <- dashboard with RSS summary card
docs/reader.html                 <- chronological feed timeline
docs/read/<entry-id>.html        <- individual article pages (pretext-rendered)
```

### Database Schema (3 new tables in meridian.db)

```sql
CREATE TABLE IF NOT EXISTS rss_feeds (
    id TEXT PRIMARY KEY,             -- slug: 'marginal-revolution'
    title TEXT NOT NULL,
    feed_url TEXT NOT NULL UNIQUE,
    site_url TEXT,
    category TEXT,                   -- 'tech', 'economics', 'quantum', etc.
    tier TEXT DEFAULT 'normal',      -- 'curated' | 'discovery'
    etag TEXT,                       -- conditional GET
    last_modified TEXT,              -- conditional GET
    last_fetched_at TEXT,
    last_status INTEGER,             -- HTTP status code
    error_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rss_entries (
    id TEXT PRIMARY KEY,             -- hash of (feed_id, guid or link)
    feed_id TEXT NOT NULL REFERENCES rss_feeds(id),
    guid TEXT,                       -- original guid from feed
    title TEXT NOT NULL,
    url TEXT,                        -- original article URL
    summary TEXT,                    -- feed-provided summary (truncated)
    content TEXT,                    -- extracted full article text (trafilatura)
    content_hash TEXT,               -- detect content changes
    author TEXT,
    published_at TEXT,               -- from feed
    fetched_at TEXT DEFAULT (datetime('now')),
    word_count INTEGER,
    read_time_minutes INTEGER
);

CREATE INDEX IF NOT EXISTS idx_rss_entries_feed ON rss_entries(feed_id);
CREATE INDEX IF NOT EXISTS idx_rss_entries_published ON rss_entries(published_at DESC);

CREATE TABLE IF NOT EXISTS rss_saved (
    entry_id TEXT PRIMARY KEY REFERENCES rss_entries(id),
    saved_at TEXT DEFAULT (datetime('now')),
    note TEXT
);
```

Rolling cleanup: entries older than 30 days deleted (except saved).

### Connector (src/connectors/rss.py)

Extends `BaseFeedConnector`. Key behaviors:
- **feedparser** for RSS/Atom parsing (handles malformed feeds)
- **Conditional GET**: stores ETag + Last-Modified per feed, sends on subsequent requests
- **trafilatura**: extracts article content from source URL for the article reader
- **Error tracking**: increments error_count on failure, exponential backoff after 3 failures

### CLI Tool (src/rss.py)

```
python -m src.rss add <url>       # auto-discover feed, prompt category, append to YAML
python -m src.rss list            # show all feeds with category, tier, frequency
python -m src.rss remove <id>     # remove feed from YAML
python -m src.rss import <opml>   # import OPML file into YAML
python -m src.rss export          # export feeds as OPML to stdout
python -m src.rss fetch           # manually trigger feed update
```

Feed discovery algorithm:
1. Fetch page HTML
2. Parse `<link rel="alternate" type="application/rss+xml">` tags
3. If none found, probe well-known paths (/feed, /rss, /atom.xml, /feed.xml, /index.xml)
4. Return list of discovered feed URLs

### Generated Pages

#### Dashboard Card (index.html)

A new "RSS: Latest" card in the masonry grid showing:
- Recent entries grouped by category (2-3 per category)
- Time-ago timestamps
- Link to reader.html

#### Reader Timeline (reader.html)

- Chronological timeline of all entries across feeds
- Grouped by category with collapsible sections
- Time-decay styling: entries fade as they age
- Click entry title → opens article reader page (docs/read/<id>.html)
- "Open original" link for the source URL
- Keyboard navigation: j/k move, o open article, O open original, s save
- Category filter tabs at top
- Canvas-rendered cards matching dashboard aesthetic

#### Article Reader (docs/read/<entry-id>.html)

- Extracted article content rendered with pretext for lightweight text layout
- Flexoki theme, IBM Plex Mono typography
- Images from original source (referenced URLs, not embedded)
- Metadata header: source, author, published date, word count, reading time
- Navigation: back to reader, previous/next article
- Clean, distraction-free — no sidebar, no comments, no ads
- Falls back gracefully if content extraction failed (shows summary + link to original)

### Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Feed parsing | `feedparser` | 22 years battle-tested, handles 99%+ of feeds |
| HTTP | `requests` (existing) | Conditional GET with ETag/Last-Modified |
| Content extraction | `trafilatura` | Best Python article extraction, handles boilerplate removal |
| Storage | SQLite (existing meridian.db) | Zero new infrastructure |
| OPML | `xml.etree.ElementTree` | stdlib, no dependency |
| Feed discovery | Custom (~40 lines) | Parse HTML link tags + probe paths |
| Text rendering | `@chenglou/pretext` | Lightweight text layout for article pages |

### Configuration (config/rss_feeds.yaml)

```yaml
rss_feeds:
  # Quantum Computing researchers (seed feeds)
  - id: scott-aaronson
    title: Shtetl-Optimized
    feed_url: https://scottaaronson.blog/?feed=rss2
    category: quantum
    tier: curated

  - id: quantum-computing-report
    title: Quantum Computing Report
    feed_url: https://quantumcomputingreport.com/feed/
    category: quantum
    tier: curated

  # More feeds added over time via CLI...

display:
  entries_per_category: 8
  max_age_days: 7
  article_retention_days: 30
```

### GitHub Actions Integration

Add RSS phase to existing workflow:

```
Step 1: Fetch metrics (existing)
Step 2: Fetch HN feeds (existing)
Step 3: Fetch RSS feeds (new)
Step 4: Extract article content (new)
Step 5: Generate dashboard + reader + article pages (updated)
Step 6: Commit + push (existing)
```

### What NOT to Build (v1)

- Full-text search across articles
- Social sharing or commenting
- Push notifications or badge counts
- AI-powered recommendations or summaries
- Podcast/video player
- Newsletter-to-feed ingestion
- Cross-source correlation with HN stories

These can be considered after using the basic reader for a month.
