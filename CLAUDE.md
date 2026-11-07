# CLAUDE.md — BoxOfficeBozo

Hobby, non-commercial site: historical domestic box office rankings **as of any date**, with a late-90s fan-site look built with modern Tailwind.

## Read first
- `ROADMAP.md`: phases
- `docs/MVP_PLAN.md`: **the build plan; work milestone by milestone, in order**
- `docs/DATA_SOURCES.md`: sources, terms, fetch etiquette
- `DATA_NOTICE.md`: the public statement of each source's terms, the disclaimer, and the takedown contact
- `docs/DESIGN.md`: visual direction (web 1.0 aesthetic, modern usability)

## Stack
- ETL: Python 3.12, `uv` (project in `etl/`), polars, duckdb, pyreadr, httpx, rapidfuzz, pytest. Package `etl/boffo_etl`, tests in `etl/tests/`.
- Site: Vite + React + TypeScript + Tailwind v4 + DuckDB-WASM + uPlot + react-router. Static, deployed to GitHub Pages.
- CI: GitHub Actions. `ci.yml` runs on PRs (guard, pytest, vitest, `checks.py`, site build). `deploy.yml` runs on push to `main`: the `data-build` job fetches, builds the Parquet and the site, and uploads the Pages artifact. Then the `deploy` job publishes it.
- Live at https://boxofficebozo.com (GitHub Pages custom domain, verified on the account; Cloudflare DNS records are DNS only, never proxied). The `SITE_BASE_PATH` repo variable is `/`. Internal names (`boffo_etl`, `BOFFO_*` env vars, the local folder) predate the BoxOfficeBozo rename and are intentional.
- Data ships to the site as Parquet in `site/public/data/`. It is **built in CI, gitignored, and published only inside the Pages artifact.**

## Data sources (and what's banned)
- Allowed: Purdue stat695data (GitHub), Wayback Machine and Common Crawl captures of Box Office Mojo pages, Wikidata (CC0, queried through QLever at qlever.dev) for titles, IMDb IDs (P345), directors and cast, BLS CPI-U (not FRED: its terms bar caching).
- **Never fetch boxofficemojo.com, imdb.com, or the-numbers.com live.** There's no live backend and there never will be. `boffo_etl/fetch.py` hard-blocks those hosts (and every redirect hop). Don't loosen that.
- **Don't use the IMDb non-commercial datasets.** Their terms forbid republishing them as an online database of movie information. IMDb IDs are fine as identifiers when they come from Wikidata P345.

## Rules
- **Fetching happens in CI, not locally.** The ETL is offline by default. A cache miss raises `FetchDisabledError` unless `BOFFO_FETCH=1`, which only the `data-build` step in `deploy.yml` sets. Raw downloads are cached in `data/raw/` and persisted between CI runs with `actions/cache`.
- Never fetch a URL that's already cached in `data/raw/`. Wait at least 5 s between requests to one host and send the project User-Agent (both built into `fetch.py`).
- **Never commit scraped or derived data.** `data/raw/`, `data/build/`, `site/public/data/`, `*.parquet`, and `*.rda` are gitignored. `make guard` (run in CI) fails if any are tracked.
- `data/manual/*.csv` are hand-curated and committed. **Every row needs a real, citable source** (publication + date + page, or a stable URL) in `source`/`source_url`. Never make up figures, round to "about right", or fill gaps by hand. Interpolation happens at build time and is flagged. `checks.py` rejects empty and placeholder sources.
- Don't silently "fix" data. Flag anomalies (decreasing cumulative totals, duplicate ranks, gaps) in `checks.py` output, and fix them via `data/manual/` overrides that cite a source.
- Rentals ≠ grosses. Keep `is_rental` / `is_estimate` / `baseline` flags all the way to the UI.
- Ranking SQL lives in `site/src/queries/*.sql` and is executed by both the browser and the Python tests. One source of truth.
- Golden tests in M6 must cite where the expected fact comes from.
- No made-up numbers anywhere on the site, including placeholder or demo tables.
- Follow `docs/DESIGN.md`: square corners, Verdana, navy header bars, dense zebra tables, underlined blue links, WCAG AA contrast, no blinking or auto-motion.
- Adding a new data source means updating `docs/DATA_SOURCES.md`, `DATA_NOTICE.md`, the fetch allowlist, and the site credits together.

## Commands
- `make setup`: `uv sync --locked` and `npm ci`
- `make etl`: build all Parquet (offline locally; fetches only in CI)
- `make check`: data-quality report
- `make test`: pytest and vitest
- `make site-dev` / `make site-build`
- `make guard`: fail if data files are tracked by git
- On Windows without `make`, run the underlying commands from the `Makefile` (e.g. `uv --directory etl run pytest`, `cd site && npm test`).

## Done means
Each milestone's **Accept** criteria in `docs/MVP_PLAN.md` pass. Note progress by ticking the milestone checklist in `README.md`.
