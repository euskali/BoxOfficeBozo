# BoxOfficeBozo

**Box office history, as it happened.**

A free hobby site that brings back the old Box Office Mojo charts, plus a "time machine": pick any film and any date to see where it ranked on the all-time lists *at that moment*. It covers nominal dollars, inflation-adjusted dollars, and estimated tickets sold, with career totals for directors and actors as of any date.

Looks like 1999. Works like 2026.

🌐 **Live:** https://boxofficebozo.com

- 🗺️ [Roadmap](ROADMAP.md)
- 🛠️ [MVP plan](docs/MVP_PLAN.md)
- 📚 [Data sources](docs/DATA_SOURCES.md)
- 🎨 [Design direction](docs/DESIGN.md)
- ⚖️ [Data notice](DATA_NOTICE.md): source terms, disclaimer, takedown requests

## MVP progress
- [x] M0 Scaffold
- [x] M1 Ingest 1982–2016
- [x] M2 Ingest 2017 → present
- [x] M3 Identity matching
- [x] M4 Credits & people
- [x] M5 Inflation & admissions
- [x] M6 Ranking engine + golden tests
- [x] M7 Site
- [ ] M8 Data notes & launch

## Working on the site
The data is built only in CI, so a fresh clone has none. Fill `site/public/data/` (gitignored) with either:
- `make pull-data`: the real tables the live site publishes (checksums verified), or
- `make sample-data`: fictional films with made-up numbers (the site shows a SAMPLE DATA banner).

Then `make site-dev`. On Windows without `make`, run `uv --directory etl run python -m boffo_etl.pull_data` and `cd site && npm run dev`.

`make site-build` is `npm run build` followed by `python -m boffo_etl.route_pages`, which writes a page file for every route (about 78,000 with the real data) so GitHub Pages serves deep links with status 200 rather than 404.

## Credits
Data from the Purdue STAT 695 dataset (Box Office Mojo weekend charts, 1982–2016), archived Box Office Mojo pages via the Internet Archive Wayback Machine and Common Crawl, Wikidata (CC0), and the U.S. Bureau of Labor Statistics. Non-commercial. Not affiliated with IMDb, Box Office Mojo, or The Numbers. See [DATA_NOTICE.md](DATA_NOTICE.md).

This repo holds code, docs, and cited hand-curated CSVs only. Data is built in GitHub Actions and published only with the site.

License: GPL-3.0 (code). Data keeps its sources' terms.
