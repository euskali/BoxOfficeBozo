# Data Sources

Status key: ✅ use in MVP · 🔜 later phase · 📚 reference/manual · ⛔ not used (terms)

BoxOfficeBozo is a **non-commercial hobby project** with a **public repo**. The repo holds code, docs, and cited manual CSVs only. Everything fetched or derived is built in CI and published only in the GitHub Pages artifact. If any of that changes, revisit this file and `DATA_NOTICE.md` first.

## Core (MVP)

| Source | What | Coverage | Terms | Status |
|---|---|---|---|---|
| **Purdue `stat695data` (`mojo.rda`)**, github.com/schloerke/stat695data, pinned to commit `7a8d5bb7bae4` (2017-04-13) | Box Office Mojo weekend charts scraped Mar 23, 2017: rank, weekend gross, theaters, **cumulative total gross**, release date, genre, MPAA, legacy Mojo id (21 columns) | 1982–2016, 116,663 rows, 13,499 releases | MIT covers the R package code. The figures themselves were scraped from Box Office Mojo | ✅ |
| **Wayback Machine** (CDX API) | Archived Box Office Mojo weekend chart pages (`/weekend/YYYYWnn/`, plus old-style chart URLs) and release pages (for IMDb `tt` ids) | 2017 → present | Internet Archive terms. No published rate limit; ~15 req/min is the unofficial ceiling, and we stay at ≤12/min. Prefix/wildcard CDX queries on this site are refused (HTTP 503), so we ask one exact URL per weekend | ✅ |
| **Common Crawl** (index.commoncrawl.org + WARC byte ranges) | The same Box Office Mojo pages, as a fallback for weekends Wayback lacks | ~2013 → present | Common Crawl terms: crawled content "may be subject to separate terms" of its owners. Don't overload the index server (it often times out; we cap index queries per run) | ✅ |
| **Wikidata** (CC0) | Films, English labels, IMDb ID (P345), legacy Box Office Mojo film ID (P1237), directors (P57), cast (P161) and voice actors (P725) with the P1545 ordinal when present, people's names and IMDb IDs, publication date (P577), genre (P136), duration (P2047) | ~14.3k films carry P1237, nearly all with P345 too; ~337k film items have P345 and P577 (Nov 2026) | CC0, no attribution required (we credit anyway). Queried through **QLever** (`qlever.dev`, the University of Freiburg's public SPARQL endpoint over the full Wikidata graph), one request at a time, ≥5 s apart, with our User-Agent; it stops queries at 30 s. The Wikidata Query Service (60 s timeout) couldn't answer a year of films in time, so it isn't used. One snapshot per month (about 120 queries), cached in `data/raw/`. Credits come from the **Wikidata API** (`www.wikidata.org/w/api.php`, `wbgetentities`, 50 films a request), the only source of statement order, which stands in for billing; only the credit statements are cached. About 324 requests a month, ≥5 s apart | ✅ |
| **BLS CPI-U** (`CUUR0000SA0`) | Monthly CPI, U.S. city average, not seasonally adjusted | 1913 → present | Public domain; cite BLS. Read from the **BLS Public Data API v1** (`api.bls.gov`, no key; up to 10 years a request, POST only, 25 requests a day): twelve ten-year windows the first time, then the current window once a week | ✅ |
| **Average ticket price history** | Annual US average ticket price | 1948, 1954, 1958, 1963, 1967, 1969, 1971, 1974–2019 and 2022 sourced (Nov 2026); other years interpolated or carried forward at build time, flagged | Facts with citations, in a manual CSV (sources below) | ✅ (manual CSV) |

## Not used, and why

| Source | Why not | Status |
|---|---|---|
| **Box Office Mojo (live site)** | IMDb's Conditions of Use ban "data mining, robots, screen scraping", and Box Office Mojo is an IMDb company. `fetch.py` blocks `boxofficemojo.com` | ⛔ |
| **IMDb non-commercial datasets** | The data "must not be altered/republished/resold/repurposed to create any kind of online/offline database of movie information", which is what a public site does. Blocked in `fetch.py`. IMDb IDs come from Wikidata P345 instead | ⛔ |
| **FRED** (CPIAUCSL) | FRED's terms bar scraping, extraction, and caching of FRED content, and its API needs a key. We use the same BLS data from BLS directly | ⛔ |
| **The Numbers / OpusData** | Licensed. The site reserves scraping and redistribution, "commercial or otherwise", to licensees. Blocked in `fetch.py` | ⛔ |
| **IMDb + Box Office Mojo on AWS Data Exchange** | Enterprise contract | ⛔ |
| **Rentrak** (formerly Comscore Movies; sold to Advaya Capital in May 2026) | Industry source of truth, studio-only | ⛔ |

## Ticket price sources (for `data/manual/ticket_prices.csv`)
Cite each row to one of these, with the table and page. Don't transcribe Box Office Mojo's own table; go to its primary sources.
- **NATO (now Cinema United)**, "Annual Average U.S. Ticket Price": the old `natoonline.org/data/ticket-price/` page now redirects to cinemaunited.org and 404s (Nov 2026). The CSV cites its Wayback Machine capture of 18 Jan 2021, which lists 1948, 1954, 1958, 1963, 1967, 1971 and every year 1974–2019 (and 1969 in a note). Its footnote: figures before 1989 are based on the CPI-W index, later ones on NATO's survey.
- **The Cinema Foundation** (NATO's research arm), *State of the Cinema Industry*, March 2023: $10.53 for 2022, and no figures for 2020 or 2021. Cited through Fortune's report of it (10 Mar 2023). Cinema United's later reports (through the Dec 2025 "Strength of Theatrical Exhibition" update) give no annual average, so 2023 on carries 2022's price forward until a sourced figure is found.
- **Historical Statistics of the United States, Millennial Edition**, Table Dh388–391, "Motion picture attendance, box office receipts, and admission prices: 1922–1998" (Cambridge University Press).
- **Period trade sources on Lantern** (lantern.mediahist.org), e.g. *Evidence Study No. 25 of the Motion Picture Industry* (1935) for 1929–1934, and *Film Daily Year Book* volumes.
- Known gaps: before 1948, the years between NATO's early rows (1949–53, 1955–57, 1959–62, 1964–66, 1968, 1970, 1972–73), 2020–21, and 2023 on. Leave them out of the CSV and let the build interpolate or carry forward (flagged) until they're found. Pre-1982 baselines of films released before 1948 need the earlier years to have admissions.

## Helpful extras (check terms before using any)

| Source | What | Notes | Status |
|---|---|---|---|
| **heike/classdata `mojo`** (R pkg, GitHub) | Mojo weekend charts scraped Sep 2018 | 2013–2018, about 31.7k rows. Could cross-check 2017–2018. Check its license first | 🔜 |
| **Wayback Machine, old Mojo** | `boxofficemojo.com/people/…`, `/alltime/adjusted.htm`, `/movies/?id=…` (archived) | Validate person rollups and adjusted rankings against what Mojo showed | 🔜 |
| **R `boxoffice` package** (CRAN) | Daily scraper for Mojo / The Numbers | Reference implementation only. Its live-scraping approach is not allowed here | 📚 |
| **TMDB API** | Lifetime worldwide revenue, budget, posters | Free non-commercial with attribution; 6-month cache limit. Re-check the terms for a public site | 🔜 |
| **Wikidata** (P2142 box office) | Lifetime grosses with qualifiers | CC0, inconsistent coverage | 🔜 |
| **Wikipedia "box office number-one films in the US" lists** | Weekly #1 film, 1948→present (pre-1982 = Variety National Boxoffice Survey) | CC BY-SA text; facts free. Great for pre-1982 #1 history | 🔜 |

## Pre-1982 / deep history (Phase 3)

| Source | What | Notes |
|---|---|---|
| **Media History Digital Library / Lantern**, lantern.mediahist.org | Scanned Variety, Film Daily, Boxoffice, Motion Picture Herald, etc. | Public domain, mostly pre-1964. OCR text; full volumes downloadable via Internet Archive |
| **Boxoffice magazine back issues** (Internet Archive, Online Books Page) | Weekly trade issues and the annual *Boxoffice Barometer* | Free scans |
| **Variety anniversary editions**, worldradiohistory.com | Annual issues with the all-time rental champs list | Free scans |
| **Books** 📚 | Finler, *The Hollywood Story* (2003) and *All-Time Box-Office Hits* (1985); Steinberg, *Reel Facts* (1982); Sackett, *Hollywood Reporter Book of Box Office Hits* (1996); *Art Murphy's Box Office Register* (annual from 1984) | Library / Internet Archive lending. Extract figures manually with page citations |

**Big caveat for old data:** until the 1970s–80s, trades reported **distributor rentals**, not box office grosses. Store them with `is_rental=true` and never mix them silently with grosses.

## Etiquette for anything fetched
- Fetch **only in CI** (`BOFFO_FETCH=1` in the `data-build` job). Locally the ETL is offline.
- Cache everything in `data/raw/` (persisted with `actions/cache`) and never re-fetch what's cached.
- At least 5 s between requests to one host, and a User-Agent that names the project and repo URL. Back off on 429/503 and honor `Retry-After`.
- Archives only for Box Office Mojo pages. Never the live site.
- Credit sources on the About page, in the footer, and in `DATA_NOTICE.md`.
