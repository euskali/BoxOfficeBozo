# boffo-etl

Python 3.12 ETL package (`boffo_etl`) for BoxOfficeBozo, managed with `uv`.

## Run

From the repo root (see the top-level Makefile for the canonical targets):

    make etl      # python -m boffo_etl.build
    make check    # python -m boffo_etl.checks
    make test     # pytest (plus site tests)

Or directly:

    uv run --directory etl pytest -q
    uv run --directory etl python -m boffo_etl.checks
    uv run --directory etl python -m boffo_etl.build

## Offline by default

The ETL never touches the network unless `BOFFO_FETCH=1` is set. The CI
data-build job sets it; local runs and tests do not. A cache miss without the
flag raises `FetchDisabledError`, and `make etl` skips that step.

Tests that need real built tables (`tests/test_data_*.py`) skip when the tables
are absent. The CI data-build job sets `BOFFO_REQUIRE_DATA=1`, which makes a
missing table (or an uncached input) fail instead.

All fetches go through `boffo_etl.fetch`: cached under `data/raw/http/`,
rate-limited per host, restricted to an allowlist (Wayback, Common Crawl,
Wikidata, BLS, GitHub). Live fetching from boxofficemojo.com, imdb.com,
the-numbers.com and related hosts is permanently blocked.

The M2 step (`sources/bom_weekend.py`) fetches about a thousand archived pages
on its first run. It stops starting new fetches after `BOFFO_FETCH_MINUTES`
(default 270) and makes at most `BOFFO_RELEASE_PAGES` (default 150) new
release-page lookups per run, within `BOFFO_RELEASE_PAGE_MINUTES` (default 45),
for stitched carry-overs and releases that grossed $1M or more.
Weekends it didn't reach are marked `pending`, `checks.py` fails on them, and
the next run continues from the cache.

Scraped or derived data is never committed: `data/raw/`, `data/build/` and
`site/public/data/` are gitignored. `data/manual/*.csv` are hand-curated, and
every row needs a real source.
