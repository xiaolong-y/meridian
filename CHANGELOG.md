# Meridian Dashboard Changelog

## 2025-12-20: Data Quality Overhaul

### Problem Identified
A data quality audit revealed that the dashboard was displaying **IMF 2030 forecasts as current values**. For example:
- US GDP Growth showed 1.8% (2030 forecast) instead of ~2.8% (2024 actual)
- US Debt/GDP showed 143% (2030 forecast) instead of ~118% (current)

The IMF DataMapper API returns data through 2030, and the code was taking the "latest" year, which meant 2030 projections.

### Changes Made

#### 1. Switched US Metrics to FRED (Primary Source)
**File:** `config/metrics.yaml`

| Metric | Old Source | New Source | FRED Series ID |
|--------|------------|------------|----------------|
| US GDP Growth | IMF | FRED | `A191RL1Q225SBEA` |
| US Inflation | IMF | FRED | `CPIAUCSL` (with YoY transform) |
| US Unemployment | IMF | FRED | `UNRATE` |
| US Real Rate (1Y) | - | FRED | `REAINTRATREARAT1YE` |
| US Real Rate (10Y) | World Bank | FRED | `REAINTRATREARAT10Y` |
| Fed Funds Rate | - | FRED | `FEDFUNDS` |
| US Debt/GDP | IMF | FRED | `GFDEGDQ188S` |

**Requires:** `FRED_API_KEY` environment variable (free from https://fred.stlouisfed.org/docs/api/api_key.html)

#### 2. Added IMF 2030 Projections as Separate Section
Created new "US Outlook (IMF 2030)" group to show forecasts alongside actuals:
- `us.gdp_growth_proj` - GDP Growth (2030f)
- `us.inflation_proj` - Inflation (2030f)
- `us.unemployment_proj` - Unemployment (2030f)
- `us.gov_debt_proj` - Debt/GDP (2030f)
- `us.current_account_proj` - Current Account (2030f)

#### 3. Clarified Real Rate Sources
- US: Now shows both 1Y and 10Y real rates from FRED/Cleveland Fed
- China/Japan: Added "(WB)" suffix to indicate World Bank source (lending rate minus inflation)

### Data Source Summary

| Region | Primary Source | Notes |
|--------|---------------|-------|
| US Economy | FRED | Actual data, requires API key |
| US Outlook | IMF | 2030 projections, no auth |
| Eurozone | ECB SDMX | Current monetary data, no auth |
| China | IMF + World Bank | Annual data, some lag |
| Japan | e-Stat + IMF + WB | Mixed sources |
| Markets | Yahoo Finance | Real-time, no auth |
| Crypto | CoinGecko | Near real-time, no auth |

### Known Data Lags
- **World Bank Real Rates:** 2-4 year lag (US 2021, Japan 5+ years)
- **IMF Annual Data:** Published with ~6 month lag
- **e-Stat (Japan):** Variable availability

### Files Modified
- `config/metrics.yaml` - Metric configurations
- `docs/CODEBOOK.html` - Data source documentation
- `docs/index.html` - Generated dashboard

### Related Reports
- `docs/2025-12-20_data-quality-audit_report.html` - Full audit findings

---

## Development Notes

### FRED API Setup
```bash
# Get free key from: https://fred.stlouisfed.org/docs/api/api_key.html
export FRED_API_KEY=your_key_here

# Or create .env file (gitignored):
echo "FRED_API_KEY=your_key_here" > .env
```

### GitHub Actions
The `FRED_API_KEY` is stored as a GitHub Secret and used in `.github/workflows/update-dashboard.yml`.

### Database Gotcha
Metric names are cached in `data/meridian.db`. If you change a metric name in `metrics.yaml` but keep the same ID, the database may retain the old name. To fix:
```bash
sqlite3 data/meridian.db "UPDATE metrics SET name = 'New Name' WHERE id = 'metric.id';"
```
Or delete the database and re-fetch all data.

### Running Locally
```bash
source .env  # Load FRED_API_KEY
python -m src.main  # Fetch all data and regenerate dashboard
```
