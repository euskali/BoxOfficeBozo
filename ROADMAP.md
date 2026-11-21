# BoxOfficeBozo — Roadmap

**What it is:** a free, non-commercial hobby site that brings back what old Box Office Mojo did well, plus one feature it never had:
**"time machine" rankings** — pick any film and any date and see exactly where it stood on every cumulative list *at that moment*
(domestic, inflation-adjusted, admissions), plus career totals and rankings for directors and actors as of that date.

Inspired by the Blank Check with Griffin & David crowd who miss the old Mojo charts.

**Ground rules**
- Hobby, no revenue, public repo. Only sources whose terms allow a public site: archives, Wikidata (CC0), and public-domain BLS data. The IMDb datasets are out because their terms forbid republishing them as a database. See `docs/DATA_SOURCES.md` and `DATA_NOTICE.md`.
- Static site: there's no server to pay for or maintain. Data ships as Parquet files and is queried in the browser with DuckDB-WASM.
- Data is fetched and built in GitHub Actions, never committed, and published only with the site.
- Every number carries its source and quality flag (actual / estimate / rental / baseline).

---

## Phase 0 — Foundations ✅ (this commit)
- Repo, roadmap, MVP plan, data source inventory, CLAUDE.md for Claude Code.

## Phase 1 — MVP: Domestic time machine, 1982 → present
Detailed task list: `docs/MVP_PLAN.md`.
- Weekend-chart snapshots 1982–2016 from an existing scraped dataset (Purdue stat695data, MIT).
- 2017 → present weekend charts from archived Box Office Mojo pages only (Wayback Machine first, Common Crawl as fallback). Box Office Mojo is never fetched live.
- Pre-1982 baseline: hand-curated lifetime grosses for the biggest older films, so all-time lists as of 1985 still include Star Wars, Jaws, etc.
- Film identity via Wikidata (legacy Mojo IDs P1237, IMDb IDs P345), with re-releases grouped under one title.
- Credits from Wikidata (CC0) → director and actor rollups.
- Three measures: nominal $, CPI-adjusted $, and estimated admissions (ticket-price-adjusted, old-Mojo style).
- Static site: film page with a rank-over-time chart and a date picker, an all-time leaderboard as of any date, person pages, and a weekend chart for any weekend.
- Look and feel: late-90s movie fan site (old GameFAQs / eeggs / Movie Mistakes era) built with Tailwind v4. Dense tables, navy header bars, Verdana, square corners, but fast, responsive and accessible. See `docs/DESIGN.md`.
- Built and deployed to GitHub Pages by GitHub Actions.

## Phase 2 — Keep it current
- Weekly scheduled run of the deploy workflow (Monday) picks up the latest archived weekend, rebuilds Parquet, and redeploys. In place since M3, early, because it also keeps the Actions download cache from expiring.
- Data-quality dashboard: unmatched titles, gaps in weekends, totals that went backward.
- Manual override files reviewed through PRs.

## Phase 3 — Deep history (pre-1982)
- Transcribe Variety / Boxoffice annual "all-time champs" and year-end lists from the Media History Digital Library (Lantern), Boxoffice back issues on the Internet Archive, and Variety anniversary issues.
- Clearly separate **rentals** from **grosses**, with a toggle and an explainer.
- Re-release history for the classics (Gone with the Wind, Snow White, Star Wars SE, E.T. 1985/2002) so their totals step up on the right dates.
- Variety National Boxoffice Survey #1s (pre-1982) as "weekly #1" history.

## Phase 4 — Worldwide and finer grain
- Lifetime worldwide totals (TMDB if its terms allow a public site; cross-checked) as a separate, clearly approximate list.
- International timelines where data exists (mostly 2000s+).
- Daily granularity for the modern era (opening day, fastest to $X records as of a date).

## Phase 5 — Fun stuff
- "Showdowns": overlay any films' cumulative curves, by days in release or by calendar date.
- Milestone history: who held #1 all-time, and when it changed hands (a "succession of champions" timeline).
- Studio, franchise and genre rollups as of a date.
- Box Office Game–style quiz mode, e.g. "guess the top 5 all-time on July 4, 1993".
- Shareable permalinks for any view (film + date + measure).

---

## Non-goals (for now)
- Ads, accounts, paywalls.
- Republishing other sites' charts wholesale. We publish *derived* rankings and credit sources.
- Real-time daily estimates.
