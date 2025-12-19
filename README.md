# Bloomberg-Lite

> **Personal Macro & Tech Intelligence Dashboard**
> Zero-cost, self-hosted aggregator combining macroeconomic data from official sources with curated Hacker News content into a single, dense, auto-updating dashboard.

[![Update Dashboard](https://github.com/peteryang/bloomberg-lite/actions/workflows/update.yaml/badge.svg)](https://github.com/peteryang/bloomberg-lite/actions/workflows/update.yaml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Data Sources](#data-sources)
- [Metrics Reference](#metrics-reference)
- [Technical Stack](#technical-stack)
- [Installation](#installation)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Development](#development)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

Bloomberg-Lite is a **radical simplicity** approach to information aggregation. It pulls critical macroeconomic indicators and technology news into a single, self-updating dashboard—with zero infrastructure costs.

**Design Philosophy:**
- **Fewer sources, better curation**: Only official data providers (no scraping)
- **Zero maintenance burden**: Fully automated via GitHub Actions
- **Radical cost efficiency**: 100% free (GitHub Actions + Pages)
- **Dense information display**: Bloomberg Terminal-inspired minimal aesthetic

**Live Dashboard:** [View Here](https://peteryang.github.io/bloomberg-lite/) *(update with your actual GitHub Pages URL)*

---

## Features

### Macro Intelligence
- **US Economy**: Fed Funds Rate, CPI (YoY), Core CPI, Unemployment, GDP Growth, Yield Curve (10Y-2Y)
- **Eurozone**: ECB Deposit Rate, HICP Inflation, Unemployment
- **Global Markets**: Brent Crude Oil, Gold, USD Trade-Weighted Index
- **World**: Global GDP Growth (World Bank)

### Tech Intelligence
- **Hacker News Feeds**:
  - Top Stories (real-time Firebase API)
  - Curated topic feeds: AI/ML, Infrastructure, Markets & Finance, China Tech
  - Algolia search with score filtering and time-based ranking

### Automation
- **Updates every 6 hours** via GitHub Actions
- **Persistent SQLite database** cached between runs (append-only for metrics, 7-day rolling window for stories)
- **Self-healing**: Graceful degradation if individual sources fail
- **Health checks**: Automated deployment verification

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     ORCHESTRATION LAYER                                 │
│                  (GitHub Actions Scheduler)                             │
│                   Runs: Every 6 hours                                   │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      DATA INGESTION LAYER                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │
│  │    FRED     │  │     ECB     │  │ World Bank  │  │ Hacker News │   │
│  │  Connector  │  │  Connector  │  │  Connector  │  │  Connector  │   │
│  │  (US data)  │  │  (EU data)  │  │  (Global)   │  │ (Tech news) │   │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘   │
│         └────────────────┴────────────────┴────────────────┘           │
│                                │                                        │
│                                ▼                                        │
│                     ┌───────────────────┐                              │
│                     │    Normalizer     │                              │
│                     │ (Unified Schema)  │                              │
│                     └─────────┬─────────┘                              │
└───────────────────────────────┼──────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      PERSISTENCE LAYER                                  │
│                  ┌───────────────────────┐                              │
│                  │       SQLite          │                              │
│                  │  - observations       │                              │
│                  │  - stories            │                              │
│                  │  - metrics metadata   │                              │
│                  └───────────┬───────────┘                              │
└──────────────────────────────┼───────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     PRESENTATION LAYER                                  │
│                 ┌────────────────────────┐                              │
│                 │ Static HTML Generator  │                              │
│                 │  (Jinja2 templates)    │                              │
│                 └───────────┬────────────┘                              │
│                             │                                           │
│                             ▼                                           │
│                 ┌────────────────────────┐                              │
│                 │    GitHub Pages        │                              │
│                 │  (Static hosting)      │                              │
│                 └────────────────────────┘                              │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
[API Sources] ──fetch──> [Connectors] ──normalize──> [SQLite DB]
                                                           │
                                                           │
                                                           ▼
[GitHub Pages] <──deploy── [Static HTML] <──render── [Jinja2]
```

### Component Interaction

```
main.py (Orchestrator)
    │
    ├──> load_configs() ──> metrics.yaml, feeds.yaml
    │
    ├──> fetch_metrics()
    │      ├──> FREDConnector.fetch_and_normalize()
    │      ├──> ECBConnector.fetch_and_normalize()
    │      └──> WorldBankConnector.fetch_and_normalize()
    │           └──> upsert_observation() ──> SQLite
    │
    ├──> fetch_feeds()
    │      ├──> HNFirebaseConnector.fetch_and_normalize()
    │      └──> HNAlgoliaConnector.fetch_and_normalize()
    │           └──> upsert_story() ──> SQLite
    │
    └──> generate_dashboard()
           └──> Jinja2 template + SQLite data ──> docs/index.html
```

---

## Data Sources

### 1. FRED (Federal Reserve Economic Data)
**Provider:** Federal Reserve Bank of St. Louis
**API:** REST API with JSON responses
**Authentication:** Free API key required
**Rate Limit:** 120 requests/minute
**Documentation:** https://fred.stlouisfed.org/docs/api/fred/

**What we fetch:**
- **Monetary Policy**: Federal Funds Rate (FEDFUNDS)
- **Inflation**: CPI (CPIAUCSL), Core CPI (CPILFESL) - transformed to YoY %
- **Labor Market**: Unemployment Rate (UNRATE)
- **Growth**: Real GDP (A191RL1Q225SBEA) - quarterly annualized
- **Yield Curve**: 10Y-2Y Treasury Spread (T10Y2Y) - key recession indicator
- **Commodities**: Brent Crude (DCOILBRENTEU), Gold (GOLDPMGBD228NLBM)
- **Currency**: Trade-Weighted USD Index (DTWEXAFEGS)

**Why it matters:** FRED is the gold standard for US economic data. Maintained by the St. Louis Fed, it aggregates data from BLS, BEA, Treasury, and other official sources with rigorous quality control.

---

### 2. ECB (European Central Bank)
**Provider:** European Central Bank
**API:** SDMX-JSON (Statistical Data and Metadata eXchange)
**Authentication:** None required (public)
**Documentation:** https://data.ecb.europa.eu/help/api/data

**What we fetch:**
- **Monetary Policy**: ECB Deposit Facility Rate (FM/M.U2.EUR.4F.KR.DFR.LEV)
- **Inflation**: Eurozone HICP All-Items Annual Rate (ICP/M.U2.N.000000.4.ANR)
- **Labor Market**: Eurozone Unemployment Rate (STS/M.I9.S.UNEH.RTT000.4.000)

**Why it matters:** The ECB is the central bank for the eurozone (19 EU countries using the euro). Its SDMX API provides harmonized statistics across member states, crucial for tracking the world's second-largest economy.

**Technical note:** SDMX uses hierarchical series keys (e.g., `M.U2.EUR.4F.KR.DFR.LEV` = Monthly, Euro Area, Euro currency, etc.). Our connector parses this structure and normalizes time periods (monthly, quarterly, annual) to YYYY-MM-DD format.

---

### 3. World Bank Indicators API
**Provider:** World Bank
**API:** REST API with JSON responses
**Authentication:** None required
**Documentation:** https://datahelpdesk.worldbank.org/knowledgebase/articles/889392

**What we fetch:**
- **World GDP Growth** (NY.GDP.MKTP.KD.ZG) for aggregate world economy (WLD)

**Why it matters:** The World Bank provides cross-country comparable data on development indicators. We use it for global aggregate metrics not available from regional sources.

**Technical note:** World Bank data is primarily annual. The API returns `[metadata, data_array]` format; our connector extracts the data array and handles null values gracefully.

---

### 4. Hacker News APIs
**Provider:** Y Combinator (YC)
**APIs:** Official Firebase API + Algolia Search
**Authentication:** None required
**Rate Limits:** Unofficial (be polite)

#### 4a. Firebase API (Official)
**Base URL:** `https://hacker-news.firebaseio.com/v0/`
**Documentation:** https://github.com/HackerNews/API

**What we fetch:**
- **Top Stories** (`/topstories.json`) - Current front page, sorted by HN ranking algorithm
- Individual story metadata (title, URL, score, comments, author, timestamp)

**Technical approach:**
1. Fetch story ID list
2. Parallel fetch individual items (ThreadPoolExecutor with 10 workers)
3. Filter to `type: "story"` (excludes jobs, polls)

#### 4b. Algolia Search API
**Base URL:** `https://hn.algolia.com/api/v1/`
**Documentation:** https://hn.algolia.com/api

**What we fetch:**
- **Topic-based feeds**: AI/ML, Infrastructure (Postgres/Rust), Markets & Finance, China Tech
- Search parameters:
  - `query`: Full-text search terms
  - `tags`: Filter by `story` (excludes comments)
  - `time_range`: Filter by recency (day/week/month/year)
  - `min_score`: Points threshold (quality filter)
  - `sort_by`: `popularity` (default) or `date`

**Why dual sources:** Firebase gives real-time rankings, Algolia enables topic curation with search and filtering. Combined, they provide both "what's hot now" and "what matters in my domains."

---

## Metrics Reference

### US Economy

| Metric | Series ID | Frequency | Unit | Transform | Why It Matters |
|--------|-----------|-----------|------|-----------|----------------|
| **Fed Funds Rate** | FEDFUNDS | Monthly | % | None | The Federal Reserve's primary monetary policy tool. Sets the baseline for all US interest rates. |
| **US CPI YoY** | CPIAUCSL | Monthly | % | yoy_percent | Consumer Price Index measures inflation. YoY removes seasonal noise. Target: ~2%. |
| **US Core CPI YoY** | CPILFESL | Monthly | % | yoy_percent | CPI excluding food & energy (volatile). Fed's preferred inflation gauge. |
| **US Unemployment** | UNRATE | Monthly | % | None | Labor market health indicator. Low unemployment = tight labor market = wage pressure. |
| **US GDP QoQ** | A191RL1Q225SBEA | Quarterly | % | None | Real GDP growth rate (annualized). The broadest measure of economic output. |
| **10Y-2Y Spread** | T10Y2Y | Daily | bp | ×100 | Yield curve spread. Inverted curve (negative) historically predicts recessions. |

### Eurozone

| Metric | Series Key | Frequency | Unit | Why It Matters |
|--------|------------|-----------|------|----------------|
| **ECB Deposit Rate** | M.U2.EUR.4F.KR.DFR.LEV | Monthly | % | The rate banks receive for overnight deposits at ECB. Sets the floor for euro area rates. |
| **Eurozone HICP YoY** | M.U2.N.000000.4.ANR | Monthly | % | Harmonized Index of Consumer Prices. ECB's inflation target: "below but close to 2%". |
| **Eurozone Unemployment** | M.I9.S.UNEH.RTT000.4.000 | Monthly | % | Labor market slack indicator. Lower = tighter labor market. |

### Global Markets

| Metric | Series ID | Frequency | Unit | Multiplier | Why It Matters |
|--------|-----------|-----------|------|------------|----------------|
| **Brent Crude** | DCOILBRENTEU | Daily | $/bbl | 1.0 | Global oil benchmark (Europe & Asia use Brent; US uses WTI). Inflation signal. |
| **Gold (London PM)** | GOLDPMGBD228NLBM | Daily | $/oz | 1.0 | Safe-haven asset. Inverse correlation with real rates. |
| **USD Trade-Weighted** | DTWEXAFEGS | Daily | index | 1.0 | Broad dollar strength vs advanced economies (proxies DXY). |

### World

| Metric | Indicator | Frequency | Unit | Why It Matters |
|--------|-----------|-----------|------|----------------|
| **World GDP Growth** | NY.GDP.MKTP.KD.ZG | Annual | % | Global economic growth aggregate (World Bank methodology). Context for regional trends. |

---

## Technical Stack

```
┌──────────────────────────────────────────────────────────────┐
│ Language:    Python 3.10+                                    │
│ Database:    SQLite 3 (file-based, append-only for metrics) │
│ Templates:   Jinja2 (HTML generation)                        │
│ HTTP:        requests (API calls)                            │
│ Config:      PyYAML (metrics.yaml, feeds.yaml)               │
│ CI/CD:       GitHub Actions (cron: 0 */6 * * *)              │
│ Hosting:     GitHub Pages (static HTML)                      │
│ Testing:     pytest + unittest.mock                          │
└──────────────────────────────────────────────────────────────┘
```

**Dependencies:**
```toml
[project]
dependencies = [
    "requests>=2.31.0",      # HTTP client
    "pyyaml>=6.0",           # YAML parsing
    "jinja2>=3.1.0",         # Template engine
    "python-dotenv>=1.0.0",  # Environment variables
]
```

**Why these choices:**
- **SQLite**: Zero-config, file-based DB perfect for append-only time series
- **Jinja2**: Industry-standard templating with auto-escaping
- **GitHub Actions**: 2,000 free minutes/month for public repos
- **GitHub Pages**: Free static hosting with CDN

---

## Installation

### Prerequisites
- Python 3.10 or higher
- Git
- FRED API key (free): https://fred.stlouisfed.org/docs/api/api_key.html

### Local Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/bloomberg-lite.git
   cd bloomberg-lite
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -e .
   # Or for development with testing tools:
   pip install -e ".[dev]"
   ```

4. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env and add your FRED_API_KEY
   ```

5. **Run the orchestrator**
   ```bash
   # Full update (fetch data + generate dashboard)
   python -m src.main

   # Fetch data only (no dashboard generation)
   python -m src.main --fetch-only

   # Generate dashboard only (from existing data)
   python -m src.main --gen-only
   ```

6. **View the dashboard**
   ```bash
   # Open docs/index.html in your browser
   open docs/index.html  # macOS
   xdg-open docs/index.html  # Linux
   start docs/index.html  # Windows
   ```

---

## Configuration

### Metrics Configuration (`config/metrics.yaml`)

Structure:
```yaml
defaults:
  cache_hours: 6          # How often to refresh
  history_points: 120     # ~10 years of monthly data

metrics:
  - id: us.fed_funds      # Unique identifier (namespace.metric)
    name: "Fed Funds Rate"
    source: fred          # Connector to use
    series_id: FEDFUNDS   # Source-specific identifier
    frequency: monthly
    unit: "%"
    decimals: 2
    multiplier: 1.0       # Unit conversion (e.g., 100 for % to bp)
    transform: null       # Optional: yoy_percent, qoq_percent

groups:                   # Dashboard display grouping
  - name: "US Economy"
    metrics: [us.fed_funds, us.cpi_yoy, ...]
```

**Adding a new metric:**
1. Find the series ID from the source (e.g., FRED: https://fred.stlouisfed.org)
2. Add entry to `metrics:` list
3. Add ID to appropriate `groups:` list
4. Run `python -m src.main` to fetch

### Feeds Configuration (`config/feeds.yaml`)

Structure:
```yaml
feeds:
  # Firebase feeds (real-time rankings)
  - id: hn_top
    name: "Top Stories"
    source: hn_firebase
    endpoint: topstories  # or: beststories, newstories
    limit: 25

  # Algolia feeds (topic search)
  - id: hn_ai
    name: "AI/ML"
    source: hn_algolia
    query: "AI"           # Full-text search
    tags: story           # Filter to stories only
    time_range: week      # day, week, month, year
    min_score: 50         # Minimum points threshold
    sort_by: popularity   # or: date
    limit: 12

display:
  primary_feed: hn_top    # Main feed to show in dashboard
  sidebar_feeds: [hn_ai, hn_infra, ...]
```

**Customizing feeds:**
- Adjust `query` for different topics
- Set `min_score` higher for quality filtering
- Use `time_range` to focus on recent content
- Combine multiple search terms: `"postgres OR sqlite OR duckdb"`

---

## Deployment

### GitHub Pages Setup

1. **Enable GitHub Pages**
   - Go to repository Settings > Pages
   - Source: Deploy from a branch
   - Branch: `gh-pages` / `root`
   - Save

2. **Configure repository secrets**
   - Settings > Secrets and variables > Actions
   - Add secret: `FRED_API_KEY` = your_api_key_here

3. **Workflow will run automatically**
   - Every 6 hours (UTC: 00:00, 06:00, 12:00, 18:00)
   - On push to `master` branch (workflow file changes)
   - Manual trigger via Actions tab > "Update Data and Deploy" > Run workflow

### Workflow Overview (`.github/workflows/update.yaml`)

```yaml
on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours
  workflow_dispatch:        # Manual trigger
  push:
    branches: [master]      # On workflow changes

jobs:
  update:
    - Checkout code
    - Setup Python 3.11
    - Install dependencies
    - Restore SQLite cache (from previous run)
    - Run data update (python -m src.main)
    - Save SQLite cache (for next run)
    - Upload docs/ to Pages artifact

  health-check:
    - Verify index.html exists in artifact
    - Exit 1 if missing (fails deployment)

  deploy:
    - Deploy artifact to GitHub Pages
```

**Key features:**
- **SQLite caching**: Database persists between runs (30-day retention)
- **Concurrency control**: Only one deployment at a time
- **Health checks**: Validates artifact before deploying
- **Secrets**: FRED_API_KEY injected securely

---

## Development

### Project Structure

```
bloomberg-lite/
├── README.md                    # This file
├── .env.example                 # Environment variables template
├── .gitignore                   # Git ignore rules
├── pyproject.toml               # Python project metadata & dependencies
├── requirements.txt             # Pip requirements (generated)
│
├── config/
│   ├── metrics.yaml             # Metric definitions & API mappings
│   └── feeds.yaml               # Hacker News feed configurations
│
├── src/
│   ├── __init__.py
│   ├── main.py                  # Orchestrator entry point
│   │
│   ├── connectors/              # Data source connectors
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract base classes
│   │   ├── fred.py              # FRED API connector
│   │   ├── ecb.py               # ECB SDMX connector
│   │   ├── worldbank.py         # World Bank API connector
│   │   └── hackernews.py        # HN Firebase + Algolia connectors
│   │
│   ├── storage/                 # Database layer
│   │   ├── __init__.py
│   │   ├── database.py          # SQLite operations (CRUD)
│   │   └── models.py            # Data models (Observation, Story, MetricMeta)
│   │
│   ├── transforms/              # Data transformations
│   │   ├── __init__.py
│   │   └── calculations.py      # YoY, QoQ, sparklines
│   │
│   └── generator/               # HTML generation
│       ├── __init__.py
│       └── html.py              # Jinja2 template rendering
│
├── templates/
│   ├── dashboard.html           # Main dashboard template
│   ├── partials/                # Reusable template fragments
│   └── static/                  # CSS/JS (if needed)
│
├── data/
│   └── bloomberg_lite.db        # SQLite database (gitignored)
│
├── docs/
│   └── index.html               # Generated dashboard (GitHub Pages)
│
├── tests/
│   ├── __init__.py
│   ├── test_connectors.py       # Connector unit tests
│   ├── test_transforms.py       # Transform function tests
│   └── test_generator.py        # HTML generation tests
│
└── .github/
    └── workflows/
        └── update.yaml          # Scheduled update workflow
```

### Database Schema

```sql
-- Macro observations (append-only, full history)
CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_id TEXT NOT NULL,        -- e.g., "us.fed_funds"
    obs_date TEXT NOT NULL,         -- YYYY-MM-DD
    value REAL NOT NULL,
    unit TEXT,                      -- %, bp, $/bbl
    source TEXT NOT NULL,           -- fred, ecb, worldbank
    retrieved_at TEXT DEFAULT (datetime('now')),
    UNIQUE(metric_id, obs_date, source)
);

-- Tech stories (rolling 7-day window)
CREATE TABLE stories (
    id INTEGER PRIMARY KEY,         -- HN item ID
    title TEXT NOT NULL,
    url TEXT,
    score INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    author TEXT,
    posted_at TEXT,
    source TEXT NOT NULL,           -- hn_firebase, hn_algolia
    feed_id TEXT NOT NULL,          -- e.g., "hn_top"
    retrieved_at TEXT DEFAULT (datetime('now'))
);

-- Metric metadata cache (latest values for dashboard)
CREATE TABLE metrics (
    id TEXT PRIMARY KEY,            -- Metric ID
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    frequency TEXT,                 -- monthly, quarterly, daily, annual
    unit TEXT,
    last_value REAL,
    last_updated TEXT,
    previous_value REAL,
    change REAL,                    -- Absolute change
    change_percent REAL             -- Percentage change
);
```

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run with coverage
pytest --cov=src tests/

# Run specific test file
pytest tests/test_connectors.py

# Run specific test
pytest tests/test_connectors.py::TestFREDConnector::test_fetch_success
```

### Code Style

```bash
# Lint with ruff
ruff check src/ tests/

# Auto-fix issues
ruff check --fix src/ tests/

# Format code
ruff format src/ tests/
```

### Adding a New Data Source

1. **Create connector** (`src/connectors/newsource.py`):
   ```python
   from .base import BaseMetricConnector, ConnectorConfig, FetchResult
   from ..storage.models import Observation

   class NewSourceConnector(BaseMetricConnector):
       SOURCE_NAME = "newsource"

       def fetch(self, config: ConnectorConfig) -> FetchResult:
           # Implement API call
           pass

       def normalize(self, config: ConnectorConfig, raw_data) -> list[Observation]:
           # Convert to Observation objects
           pass
   ```

2. **Register in orchestrator** (`src/main.py`):
   ```python
   from .connectors.newsource import NewSourceConnector

   connectors = {
       "fred": FREDConnector(),
       "newsource": NewSourceConnector(),  # Add here
   }
   ```

3. **Add metrics** (`config/metrics.yaml`):
   ```yaml
   - id: category.metric_name
     name: "Display Name"
     source: newsource
     frequency: monthly
     unit: "%"
     # ... source-specific fields
   ```

4. **Test**:
   ```python
   # tests/test_connectors.py
   class TestNewSourceConnector:
       def test_fetch(self):
           # Mock API calls, test normalization
           pass
   ```

---

## Contributing

Contributions welcome! Please follow these guidelines:

1. **Fork the repository**
2. **Create a feature branch** (`git checkout -b feature/amazing-feature`)
3. **Make your changes**
   - Add tests for new functionality
   - Update documentation if needed
   - Follow existing code style (ruff)
4. **Commit** (`git commit -m 'Add amazing feature'`)
5. **Push** (`git push origin feature/amazing-feature`)
6. **Open a Pull Request**

**Areas for contribution:**
- Additional data sources (BLS, BEA, OECD, BIS, IMF)
- Enhanced visualizations (interactive charts)
- Alert system (email/webhook when metrics cross thresholds)
- Mobile-optimized UI
- RSS feed generation
- Historical data backfill tools

---

## License

MIT License - see [LICENSE](LICENSE) file for details.

**Disclaimer:** This project is for personal use and educational purposes. Data is sourced from public APIs and is subject to their respective terms of service. Not affiliated with Bloomberg L.P.

---

## Acknowledgments

- **Data Providers**:
  - [Federal Reserve Bank of St. Louis (FRED)](https://fred.stlouisfed.org)
  - [European Central Bank (ECB)](https://data.ecb.europa.eu)
  - [World Bank](https://data.worldbank.org)
  - [Hacker News (Y Combinator)](https://news.ycombinator.com)
  - [Algolia HN Search](https://hn.algolia.com)

- **Inspiration**:
  - Bloomberg Terminal's dense information display
  - Patrick Collison's [Fast](https://patrickcollison.com/fast) philosophy
  - The "do one thing well" Unix philosophy

---

**Built with Python, SQLite, and a love for dense information design.**

*Last updated: 2025-12-18*
