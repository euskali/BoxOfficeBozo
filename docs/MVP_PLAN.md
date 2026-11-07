# MVP Plan — Domestic Time Machine (1982 → present)

This is the build plan for Claude Code. Work through the milestones **in order**, and finish each one's acceptance criteria before moving on.
Read `CLAUDE.md`, `docs/DATA_SOURCES.md`, `DATA_NOTICE.md`, and `docs/DESIGN.md` first.

## MVP definition of done
A static site on GitHub Pages where a visitor can:
1. Search for any film released domestically since 1982, or a major pre-1982 film.
2. Pick any date (weekend granularity) and see the film's **all-time domestic rank** at that date in three measures: **Nominal $**, **CPI-adjusted $**, and **Estimated admissions**.
3. See a chart of that film's all-time rank over time.
4. View the **all-time top 100 as of any date**.
5. View a **director or actor page** with their career total and rank among peers as of any date.
6. View the actual **weekend chart** for any weekend since 1982.

All of it is served as static files, with data queried client-side through DuckDB-WASM.

---

## Architecture

```
etl/                      Python 3.12 uv project
  boffo_etl/
    fetch.py              cached, polite fetcher; offline unless BOFFO_FETCH=1 (CI); hard-blocks live BOM/IMDb hosts
    manual.py             schemas + citation rules for data/manual/*.csv
    sources/
      stat695.py          1982–2016 weekend snapshots (Purdue stat695data mojo.rda)
      bom_weekend.py      2017→present weekend charts from archives only (Wayback first, Common Crawl second)
      wikidata.py         films, IMDb IDs (P345), legacy Mojo IDs (P1237), directors (P57), cast (P161); CC0
      cpi.py              CPI-U monthly, BLS series CUUR0000SA0 (public domain)
    match.py              release → title matching via Wikidata + overrides
    build.py              orchestrates; writes data/build/*.parquet and site/public/data/*.parquet
    checks.py             data-quality checks (also run in CI)
  tests/                  pytest (offline; synthetic fixtures only)
data/
  manual/                 COMMITTED hand-curated CSVs; every row cites a real source (see below)
  raw/                    gitignored downloads; persisted between CI runs with actions/cache
  build/                  gitignored intermediate outputs
site/                     Vite + React + TypeScript + Tailwind v4 + DuckDB-WASM (Vitest tests in src/)
  src/queries/            ranking SQL shared by the browser and pytest
  public/data/            gitignored; final Parquet built in CI, shipped only in the Pages artifact
scripts/check-no-data.sh  `make guard`: fails if data files are tracked by git
.github/workflows/        ci.yml (PRs) · deploy.yml (push to main: data-build → deploy)
DATA_NOTICE.md            source terms, not-affiliated disclaimer, takedown contact
```

**Why static and DuckDB-WASM:** total data is small (~150k snapshot rows, ~25k titles, ~100k credits). DuckDB's `ASOF JOIN` computes "latest cumulative total on or before date D" for every film in milliseconds, in the browser. There's no server and no hosting bill.

## Data pipeline and publishing

The repo is public, so it holds **code, docs, and cited manual CSVs only**. No scraped or derived data is ever committed.

| Stage | Where it runs | Where the output lives |
|---|---|---|
| Fetch (Wayback, Common Crawl, Wikidata, BLS, stat695data) | CI only: the `data-build` job in `deploy.yml`, the one step with `BOFFO_FETCH=1` | `data/raw/`, persisted with `actions/cache` (never in git) |
| Build Parquet | CI (`make etl`) | `site/public/data/` (gitignored) |
| Test + check | PRs (`ci.yml`) and `data-build` | n/a |
| Publish | `data-build` uploads `site/dist` as the Pages artifact. Then the `deploy` job publishes it | GitHub Pages only |

- **Locally the ETL is offline.** A cache miss raises `FetchDisabledError`. Unit tests use small synthetic fixtures, never real scraped data.
- **Raw cache:** restored by prefix `raw-v1-`. It's saved under `raw-v1-<fingerprint of the file list>` only when new files were fetched, and saved even if the build fails so a long first fetch isn't lost. GitHub evicts caches unused for 7 days or past the repo's size limit. The next run then re-fetches politely. That's slow but correct. Bump the prefix to `raw-v2-` to force a clean fetch.
- **PR CI has no data.** Tests that need built tables skip when they're absent. The `data-build` job runs them for real (from M1, set `BOFFO_REQUIRE_DATA=1` there so a missing table fails instead of skipping).
- **`make guard`** fails CI if `*.parquet`, `*.rda`, `data/raw/`, `data/build/`, or `site/public/data/` files are tracked.

---

## Data model (Parquet tables shipped to the site)

**`titles.parquet`**: one row per *film* (re-releases grouped)
`title_id` (IMDb tconst taken from Wikidata P345, or `bb_xxxx` if unmatched) · `wikidata_qid` (nullable) · `title` · `year` · `release_date` (original domestic) · `distributor` · `genres` · `mpaa` · `pre1982_baseline_gross` (nullable) · `baseline_source`

**`releases.parquet`**: one row per *release* (original, 1985 re-release, special edition…)
`release_id` (`legacy:<movie_id>` for stat695 and old-style 2017–2019 pages, `bom:<rl id>` for new-site releases) · `title_id` · `label` (e.g. "1997 Special Edition", or Box Office Mojo's own "2019 re-release"; null for an original) · `release_date` · `source_key` (legacy mojo id / BOM rl id) · `source` (`stat695` | `bom_weekend`) · `title` (as charted) · `distributor` · `genres` · `mpaa` · `first_weekend` · `last_weekend` · `weekends` (both counted over every source's snapshots) · `is_rerelease` · `rerelease_reason` (which detection rule fired: see `stat695.detect_rereleases`; `bom_label` for a Box Office Mojo re-release label) · `parent_release_id` · `group_source` (`auto` | `manual`) · `bom_release_id` (the new-site `rl` id; set on a stat695 release too when M2 stitched a carry-over film to it)
- Until M3 matches titles, `title_id` is a provisional `bb_` id from the root release's legacy id (or `bb_rl…` for a new-site release), so detected re-releases already share one. New-site releases whose archived release pages link the same IMDb title share one too.

**`snapshots.parquet`**: one row per release per weekend it charted
`weekend_end` (date, Sunday; the chart's own end date, and `checks.py` flags any that aren't Sundays) · `release_id` · `title_id` · `rank` · `weekend_gross` · `theaters` · `total_gross` (cumulative for that release) · `weeks` (weekends in release, as charted) · `source` (`stat695` | `wayback` | `commoncrawl`) · `capture_url` (the archive capture the row came from; null for stat695) · `is_estimate`

**`title_cume.parquet`**: precomputed per title per weekend where it changed (this drives the time machine)
`title_id` · `as_of` (weekend_end) · `cume_nominal` · `cume_cpi` (in constant dollars of a fixed base month; see Inflation) · `cume_admissions`
- `cume_nominal` = baseline + sum over releases of the latest `total_gross` ≤ as_of.
- Built from period deltas: for each release, `delta = total_gross - previous total_gross`. Each delta is deflated by the CPI of its weekend month and divided by the average ticket price of its year. Then take cumulative sums.
- Add one row per title at its first appearance. Pre-1982 baseline titles get a row at `1982-01-01` carrying the baseline.

**`people.parquet`** `person_id` (Wikidata QID) · `imdb_id` (nconst from Wikidata P345, nullable) · `name` (Wikidata English label)
**`credits.parquet`** `title_id` · `person_id` · `role` (`director` | `actor`) · `billing` (int: the P1545 series-ordinal qualifier when present, else Wikidata statement order; null for directors) · `billing_source` (`p1545` | `statement_order`)
**`cpi.parquet`** `month` · `cpi`  **`ticket_prices.parquet`** `year` · `avg_price` · `source` · `is_interpolated`

Credits and titles come from **Wikidata (CC0)**, not the IMDb datasets. IMDb's non-commercial terms say the data "must not be altered/republished/resold/repurposed to create any kind of online/offline database of movie information", which a public site would do. IMDb IDs appear only as identifiers, read from Wikidata P345.

### Committed manual CSVs (`data/manual/`)
**Every row needs a real, citable source**: a publication with its date and page, or a stable URL (an archived copy is best). No made-up, rounded-to-feel-right, or hand-interpolated figures. `boffo_etl/manual.py` enforces exact headers, types, unique keys, a non-placeholder `source`, and an http(s) `source_url` when given. `make check` fails on violations. The files start with headers only, and rows are added as they're sourced.
- `ticket_prices.csv` (`year,avg_price_usd,source,source_url,notes`): annual US average ticket price, reported years only. Prefer Cinema United (formerly NATO) figures and published statistical compendia. Don't transcribe Box Office Mojo's table. Gap years are interpolated **at build time** and flagged `is_interpolated` in `ticket_prices.parquet`. They're never written into the CSV.
- `pre1982_baseline.csv` (`title,release_year,wikidata_qid,title_id,gross_usd,as_of,is_rental,source,source_url,notes`): the ~150 highest-grossing pre-1982 films, with domestic lifetime gross *as of Dec 31, 1981* (nominal) and an `is_rental` flag. Cite a dated publication (e.g. a specific Variety issue and page). Most period figures are **rentals**, so mark them so and never convert them silently. This is what keeps all-time lists as of 1984 correct (Star Wars, Jaws, The Exorcist, Gone with the Wind, etc.). Note that later re-release grosses (e.g. Star Wars 1982 re-release) come from snapshots and add on top of the baseline. Don't double count.
- `id_overrides.csv` (`source_key,title_id,wikidata_qid,release_label,source,source_url,notes`): `source_key` → `title_id` for matches the matcher gets wrong or can't make. `source` is the evidence (e.g. the Wikidata item and the archived chart page).
- `title_groups.csv` (`source_key,title_id,release_label,source,source_url,notes`): explicit re-release groupings where automatic grouping fails.

---

## Milestones

### M0 — Scaffold (½ day)
- `uv` project for `etl/` (deps: polars, duckdb, pyreadr, httpx, rapidfuzz, pyarrow, pytest).
- `boffo_etl/fetch.py`: cache-first, offline unless `BOFFO_FETCH=1`, per-host ≥5 s spacing, project User-Agent, retries. It hard-blocks boxofficemojo.com / imdb.com / imdbws.com / the-numbers.com on every redirect hop and allowlists archive, Wikidata, BLS, and GitHub hosts.
- `boffo_etl/manual.py` + `checks.py`: manual CSV schemas and citation rules; empty (header-only) manual CSVs.
- `site/`: Vite + React + TS + Tailwind v4 + `@duckdb/duckdb-wasm` + uPlot + react-router + Vitest.
- `.gitignore`, `Makefile` with `setup`, `etl`, `check`, `test`, `site-dev`, `site-build`, `guard`.
- GitHub Actions: `ci.yml` (PRs: guard, pytest, vitest, `checks.py`, site build) and `deploy.yml` (push to `main`: `data-build` job with the raw-download cache, then a `deploy` job to Pages).
- `DATA_NOTICE.md`, with a takedown issue template.
- **Accept:** `make test` passes (with placeholder tests); the site dev server shows a "Hello 1999" page in the theme from DESIGN.md; the workflows are valid and `make guard` passes.

### M1 — Ingest 1982–2016 (stat695data)
- Fetch `mojo.rda` from `https://github.com/schloerke/stat695data` (MIT, Purdue STAT 695) via `fetch.py` in CI. It's cached in `data/raw/` and never committed. Pin the commit SHA in the URL so the input is reproducible. (Pinned to `7a8d5bb`; the build also checks the file's git blob id.)
- Unit-test the parser against a tiny **synthetic** `.rda`/DataFrame fixture built in the test, not a slice of the real file.
- Read with `pyreadr`. Columns include: year, week, rank_this_week, title, studio, weekend_gross, theater_count, total_gross, week_num, movie_id (legacy Mojo id like `ongoldenpond`), start_date, end_date, release_date, genres, mpaa. 116,663 rows, 13,499 movie_ids; years 1982–2016 (verify; coverage may extend into early 2017).
- Normalize to the `snapshots` schema (weekend_end = `end_date`). Each legacy `movie_id` becomes one `release`.
- Detect re-releases: legacy ids or titles containing "re-release", "(Special Edition)", "(3D)", "(IMAX)" style suffixes, or a `release_date` far later than an earlier same-title release.
  - *Learned from the real data (Nov 2026):* Box Office Mojo reuses titles for remakes and unrelated films, and its legacy ids follow the title. A same-title match on its own was wrong in all 79 cases, and a late first chart meant late tracking, not a re-release. So only title wording and 3D/IMAX suffixes mark a re-release, and it links to an earlier release only when the distributor matches or that release is itself a re-issue. See `stat695.detect_rereleases`; fix the rest in `title_groups.csv` or through M3.
- **Accept:** snapshot count matches the source. No weekend has duplicate ranks. `total_gross` is non-decreasing per release (log and flag violations rather than fixing them silently).

### M2 — Ingest 2017 → present
- Implement `bom_weekend.py` with two **archive** backends behind one interface. There is no live backend: boxofficemojo.com is never fetched directly, and `fetch.py` blocks it.
  1. **Wayback** (default): one CDX query (prefix `boxofficemojo.com/weekend/`, `statuscode:200`) lists every capture of `/weekend/{YYYY}W{WW}/`. For each weekend, fetch the capture *closest after* the weekend's Monday + 7 days (actuals, not Sunday estimates). For 2017 to Oct 2019, also accept old-style chart URLs captured at the time.
  2. **Common Crawl** (fallback for weekends Wayback lacks): look up the same URLs in the CC index (`index.commoncrawl.org`) and read the single WARC record by byte range from `data.commoncrawl.org`.
- Politeness: `fetch.py` spaces requests ≥5 s per host (12/min), which stays under the Wayback Machine's unofficial ~15/min limit. Back off on 429/503. The first full run takes about an hour; after that, runs hit the cache.
- Record `source` (`wayback` | `commoncrawl`) and `capture_url` on every snapshot row so each number traces back to an archived page.
- Parse the weekend table: rank, release name, BOM release id (`rl…`), weekend gross, theaters, total gross, weeks, distributor. Archived release pages link to IMDb `tt` ids, so collect them from the same archives (cached) for matching.
- Stitch at the 2016/2017 boundary. Legacy `movie_id` and new `rl` ids are different keys, so carry-over films must be linked through matching (M3).
- Parser tests use hand-written **synthetic** HTML that mimics the table structure, not saved copies of real pages.
- **Accept:** every weekend from 1982W01 through the latest completed weekend exists, or is listed in the `checks.py` gap report as having no capture in either archive. Carry-over films (e.g. late-2016 releases) have continuous `total_gross`.
- *Learned from the archives (Nov 2026):*
  - Box Office Mojo numbers weekends by Friday: `2020W01` is the weekend of the year's first Friday (Jan 3–5, 2020), and years with 53 Fridays have a `W53`. Holiday weekends are charted Friday–Sunday on the new site.
  - The Wayback CDX server refuses prefix and wildcard queries on this site (HTTP 503), so M2 asks one exact URL per weekend, in time windows. Windows that have ended are cached for good. The open window is asked again daily for weekends under 60 days old, and monthly otherwise, so a page archived later still turns up. New-style pages for 2017–2019 weekends exist (the redesigned site serves every year), but they were captured from November 2019 on.
  - The Common Crawl index often times out (HTTP 504). A weekend that Wayback lacks and the index couldn't be read for is `unchecked`, not a gap.
  - Stitching doesn't wait for M3. The last four stat695 weekends are read again as new-style pages, and their rows are matched to the stat695 rows of the same weekend by equal weekend or total gross (with the title as a tiebreak). A film that was already in release when it first charted after the boundary, and that missed those weekends, links to a same-titled stat695 release when its totals carry on (`continuity`). `bom_weekend_links.parquet` records every link.
  - Release pages are read in priority order (stitched carry-overs, then by gross, down to $1M), at most `BOFFO_RELEASE_PAGES` new lookups per run, so a run stays inside the job timeout. Later runs continue from the cache. Smaller releases are left to M3's title matching.
  - The Wayback Machine answered at about 13 s per request on the first full run (1,225 requests in 270 minutes), so it took two runs: the first stopped at its time limit with 36 weekends pending, and the re-run finished from the cache.

### M3 — Identity matching (releases → Wikidata film → IMDb ID)
- `sources/wikidata.py` (CC0): use SPARQL (WDQS or QLever) to list film items that have an IMDb ID (P345) and/or a legacy Box Office Mojo film ID (P1237). Then fetch their English labels, aliases, P577 publication dates, P136 genres, and P2047 durations in batches of 50 with `wbgetentities`. All of it is cached, and the requests carry the project User-Agent per Wikimedia policy.
- `title_id` = the item's P345 `tt` id (identifier only; no IMDb dataset is used). Items without P345 get a `bb_` id.
- For new-site releases, map the archived release page's `tt` id to the Wikidata item via P345.
- For legacy releases, **first** match directly where Wikidata's P1237 equals the legacy `movie_id`. Otherwise fuzzy-match the normalized title (`rapidfuzz`) against labels and aliases, with publication year (prefer the US P577 date) within ±1 of the release year and duration/genre as tiebreakers. Strip re-release suffixes before matching.
- Write `data/build/match_report.csv` (score, candidates) and apply `data/manual/id_overrides.csv`.
- Fixing a wrong or missing Wikidata statement upstream (with a reference) beats a local override. Use an override only when that isn't possible.
- **Accept:** ≥ 97% of total nominal gross is matched to a tconst, and 100% of the top 1,000 grossing releases. Unmatched releases keep a `bb_` id and still appear on the site.

### M4 — Credits and people (Wikidata)
- Directors from P57 and cast from P161 on the matched film items. `wbgetentities` returns claims in statement order. Billing = the P1545 (series ordinal) qualifier when present, else statement order. Store `billing_source` so the UI and checks can tell them apart.
- People: `person_id` = QID, `name` = English label, `imdb_id` = the person's P345 `nm` id when present.
- Actor rollup rule (configurable; default **top 4 billed**). Directors: all credited directors.
- `checks.py` reports the share of titles with ≥1 director and ≥4 cast, and warns on top-1,000 titles with no director.
- **Accept:** spot checks pass. Spielberg's titles include Jaws, E.T. and Jurassic Park. Tom Hanks has Toy Story and Forrest Gump, within his top 4 billed.

### M5 — Inflation and admissions
- CPI-U monthly from BLS (series `CUUR0000SA0`, U.S. city average, not seasonally adjusted, 1913 onward; public domain, cite BLS), fetched in CI into `cpi.parquet`. Use the BLS Public Data API (v1 needs no key but allows 10 years per query and 25 queries per day, so about 12 calls cover 1913 onward) or the `download.bls.gov` flat file. Don't use FRED: its terms bar scraping and caching its content.
- `ticket_prices.csv` (sourced years only) into `ticket_prices.parquet`. Linearly interpolate gap years at build time and set `is_interpolated=true` with `source` naming the two bracketing rows.
- Build `title_cume` with three measures (see the data model). Store `cume_cpi` in constant base-month dollars. The site rescales to "dollars of the selected date" or "today's dollars" with a toggle.
- Baseline films: CPI and admissions from their release year (approximation; flag `baseline=true`).
- **Accept:** unit tests cover delta deflation on a hand-computed 3-weekend example. Admissions for a known film are within ±5% of a published estimate (document which one).

### M6 — Ranking engine (shared SQL)
- Put the queries in `site/src/queries/*.sql` and run the identical SQL in Python tests against the same Parquet.
- Pin Python `duckdb` to the same engine version that `@duckdb/duckdb-wasm` bundles, and add a test that compares `SELECT version()` (pinned in `site/package.json`). In M0 they differ: wasm 1.33.1-dev57 bundles a 1.4/1.5-era engine, while Python resolved duckdb 2.0.
  - `leaderboard(as_of, measure, limit, offset, filters)`: ASOF JOIN of titles × latest `title_cume` ≤ as_of, rank with `RANK()`.
  - `film_rank_timeline(title_id, measure)`: the film's rank at every weekend since release. Precompute per title at build time if it's too slow client-side, stored as `rank_timeline/{title_id}.parquet` or one partitioned file.
  - `person_totals(as_of, role, measure)` and `person_rank`.
  - `weekend_chart(weekend_end)`.
- Golden tests need built data, so they skip in PR CI and run in the `data-build` job before every deploy.
- **Golden tests** (verify each against a cited source before locking in, and fix the data if one fails):
  - Domestic nominal #1 all-time switches from Star Wars to E.T. during E.T.'s 1982–83 run.
  - Titanic becomes #1 domestic nominal in spring 1998.
  - Avatar passes Titanic domestic nominal in early 2010.
  - Star Wars: The Force Awakens becomes #1 domestic nominal in January 2016.
  - On the admissions measure, Gone with the Wind stays #1 throughout (requires the baseline).
- **Accept:** golden tests pass. The leaderboard for any date returns in < 300 ms in the browser on a mid-range laptop.

### M7 — Site (per DESIGN.md)
- Pages: Home, Film, Leaderboard, Person, Weekend Chart, About/Data Notes.
- URL state for everything (`/film/tt0120338?date=1998-04-05&m=admissions`) so views are shareable.
- Search: client-side over titles and people (a small prebuilt index JSON, or DuckDB `ILIKE`), keyboard-first.
- Loading: lazy-load DuckDB-WASM and Parquet. Show a 90s-style "Loading… please wait" box with a progress bar.
- Accessibility: WCAG AA contrast, real tables with `<th scope>`, focus styles, `prefers-reduced-motion`.
- Local development data: the ETL can't fetch locally, so add `make sample-data`. It writes a small synthetic dataset (obviously fictional titles, never deployed) into `site/public/data/`. Optionally add `make pull-data` to copy the Parquet already published on the deployed site.
- **Accept:** Lighthouse scores ≥ 90 for Performance and Accessibility. All six key screens work on mobile and desktop.

### M8 — Data notes and launch
- About page in monospace FAQ style: sources and licenses (mirroring `DATA_NOTICE.md`), what "domestic" means (US + Canada), estimates vs actuals, the baseline approach, CPI vs admissions, re-release grouping, known gaps, and how to request a takedown or correction.
- Footer credits: Purdue stat695data, Internet Archive Wayback Machine, Common Crawl, Wikidata (CC0), BLS, plus the not-affiliated line.
- GitHub Pages deploys from M0 on, at the custom domain https://boxofficebozo.com (Cloudflare DNS, records set to DNS only; the `SITE_BASE_PATH` repo variable is `/`).
- **Accept:** from an empty Actions cache, `deploy.yml` runs end to end (`data-build` → `deploy`) and the deployed site works. A fresh clone passes `make setup && make test && make site-build`. `DATA_NOTICE.md` and the About page list exactly the sources the build uses.

---

## Explicitly out of MVP
Worldwide/international, daily grosses, pre-1982 week-by-week history, studio/franchise/genre rollups, quiz mode, weekly auto-update Action (Phase 2). See `ROADMAP.md`.

## Open decisions (defaults chosen; change anytime)
| Decision | Default |
|---|---|
| Re-releases | Grouped into the title's lifetime total (Mojo convention); release-level view available on the film page |
| Actor credit rule | Top 4 billed (Wikidata P1545 ordinal, else statement order) |
| Credits source | Wikidata (CC0); IMDb datasets not used (their terms forbid republishing as a database) |
| Takedown contact | GitHub issue using the "Takedown or correction request" template |
| Weekend estimates vs actuals | Prefer actuals; store an `is_estimate` flag |
| Date granularity | Weekend (Sunday end date); the date picker snaps to the nearest prior weekend |
| CPI display | "Today's dollars" default, toggle to "dollars of selected date" |
