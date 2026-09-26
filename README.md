# ai-deflation-check

Public-data test of the claim "AI is obviously deflationary". Conclusion and tables: [FINDINGS.md](FINDINGS.md). Interactive charts: https://pvijeh.github.io/ai-deflation-check/

Three questions, each with its own fetcher and its own section in the findings:

| question | data | script |
|---|---|---|
| Are prices people pay falling? (no CPI) | Zillow ZHVI/ZORI, Case-Shiller, FAO food indices, World Bank commodity "pink sheet", EIA retail electricity, BLS producer price indices for software publishers and hosting (government-reported; kept as a labelled comparison line, not primary evidence), hand-compiled streaming list prices | `scripts/fetch_prices.py` |
| Are software vendors delivering more for less? | SEC XBRL 10-K facts for 38 US software companies (revenue, cost of revenue, R&D, S&M, operating income, stock comp); hand-compiled SaaS list prices and LLM API token prices | `scripts/fetch_sec.py` |
| How big a goods-price drop would offset the AI spend? | 10-K capex for Amazon, Alphabet, Microsoft, Meta, Oracle; NVIDIA revenue; BEA nominal PCE goods / PCE / GDP / info-equipment investment via FRED | `scripts/fetch_ai_spend.py` |
| Is the effect visible where it should be? | BLS detailed-industry labor productivity and PPI for AI-exposed vs unexposed industries; OECD real GDP per hour for US vs euro area, UK, Japan, Germany, France, Canada | `scripts/fetch_productivity.py` |
| Is software getting more reliable? | Full status-page incident histories for AWS, Google Cloud, Cloudflare, GitHub, Datadog (live APIs plus Internet Archive for the parts providers no longer serve) | `scripts/fetch_incidents.py` |

## Run it

```
uv sync
make all          # fetch everything (~10 min, mostly the Internet Archive), then analyse
make analyze      # re-run analysis only, from cached raw data
```

Outputs: `data/processed/*.csv` (normalised series and `summary_*` tables), `charts/*.png`.
Raw downloads land in `data/raw/` and are reused unless you pass `--refresh` to a fetcher.

## Data notes, read before quoting anything

**Incidents.** Counts are what providers chose to post, not measured downtime. Comparable across the whole 2015–2025 period only for Cloudflare (v3 history API) and GitHub/Datadog (Statuspage `history.json`). AWS is reconstructed from Internet Archive copies of the old `status.aws.amazon.com/data.json` and ends March 2023; the replacement Health Dashboard has no public history. Google Cloud's `incidents.json` is a rolling window, reconstructed from ~2-monthly archive snapshots; its content changed shape in 2021 (per-product entries) and shrank from ~360 to ~20 entries during 2025, so GCP is only treated as comparable for 2021–2024. Maintenance posts are excluded by title. Duration stats use only incidents with an end time between 5 minutes and 7 days.

**Prices.** None of the price series is a CPI. Zillow and Case-Shiller are transaction-based indices; FAO and World Bank are world commodity prices in nominal USD; EIA electricity is average revenue per kWh, annual; BLS PPI series measure the price *received by sellers* (FRED mirrors `PCU511210511210` and `PCU5182105182101`). Streaming, SaaS and LLM prices in `data/manual/` are hand-compiled from vendor announcements with a source URL per row; they are US list prices for a named plan and have not been independently re-verified.

**SEC panel.** Annual 10-K facts from the XBRL company-facts API. Fiscal years are keyed by period-end year (Salesforce's FY ending Jan 2025 shows as 2025). Where a company switched revenue tags (ASC 606) the tags are unioned. Oracle is excluded from gross-margin stats because it tags no total cost of revenue. Aggregates in the findings use only the 32 companies with complete FY2019–2025 data; that is an incumbent, survivor-biased panel.

## Layout

```
scripts/common.py           paths, HTTP session, Internet Archive helpers
scripts/fetch_incidents.py  -> data/processed/incidents.csv
scripts/fetch_prices.py     -> data/processed/prices_monthly.csv
scripts/fetch_sec.py        -> data/processed/sec_software_panel.csv
scripts/fetch_ai_spend.py   -> data/processed/ai_spend.csv
scripts/fetch_productivity.py -> data/processed/productivity.csv
scripts/analyze.py          -> data/processed/summary_*.csv, charts/*.png
data/manual/                hand-compiled price tables (streaming, SaaS, LLM tokens)
```
