# Data Notice

BoxOfficeBozo is a free, non-commercial hobby project. This notice says where the site's data comes from, what terms each source sets, and how to ask for something to be removed or corrected.

## Not affiliated
BoxOfficeBozo is an independent fan project. It is **not affiliated with, endorsed by, or sponsored by** IMDb.com, Inc., Box Office Mojo, IMDbPro, Amazon, The Numbers / Nash Information Services, the Internet Archive, Common Crawl, the Wikimedia Foundation or Wikidata, the University of Freiburg or QLever, the U.S. Bureau of Labor Statistics, Cinema United (formerly NATO), Purdue University, or any film studio or distributor.

Box Office Mojo and IMDb are trademarks of IMDb.com, Inc. Other trademarks belong to their owners. Film titles and people's names are used only to identify the films and people they refer to.

## What this repository contains
- Code (GPL-3.0) and documentation.
- `data/manual/*.csv`: hand-curated facts. Each row cites a published source.
- **No scraped or derived data.** Raw downloads and built data files are produced in GitHub Actions and published only as part of the website build. CI fails if such files are ever committed.

## Sources and their terms

### Box office figures, 1982–2016: Purdue STAT 695 dataset
- **What:** weekend chart figures (rank, weekend gross, theater count, cumulative gross, release date, genre, rating) from the `stat695data` R package by Barret Schloerke (https://github.com/schloerke/stat695data). It was compiled from Box Office Mojo on March 23, 2017.
- **Terms:** the package is released under the MIT license. That license covers the package. The underlying figures come from Box Office Mojo.
- **Our use:** we publish facts (numbers, dates, ranks) and our own calculations from them. We don't reproduce Box Office Mojo's pages, text, or design.

### Box office figures, 2017–present: archived Box Office Mojo pages
- **What:** weekend chart figures read from archived copies of Box Office Mojo pages held by the Internet Archive's Wayback Machine (https://web.archive.org) and Common Crawl (https://commoncrawl.org). Each figure records the archive capture it came from.
- **We never fetch boxofficemojo.com or imdb.com directly.** IMDb's Conditions of Use (https://www.imdb.com/conditions) prohibit robots and scraping on its sites, and our fetcher blocks those hosts.
- **Terms:** Internet Archive Terms of Use (https://archive.org/about/terms.php). Common Crawl Terms of Use (https://commoncrawl.org/terms-of-use), which note that crawled content may be subject to its owners' own terms. Rights in the original pages stay with their owners.
- **Our use:** the same as above, facts and our own calculations only.

### Films, directors, and cast: Wikidata
- **What:** film titles, release dates, genres, directors, cast, and identifiers. IMDb IDs (Wikidata property P345) are used only as identifiers and links.
- **How:** we query Wikidata through QLever (https://qlever.dev), a public SPARQL endpoint run by the University of Freiburg, once a month. Each release is matched to a Wikidata film by Wikidata's own Box Office Mojo and IMDb ID statements, or by title and year.
- **Terms:** Wikidata's structured data is released under CC0 1.0 (https://www.wikidata.org/wiki/Wikidata:Licensing). Attribution isn't required, but we credit Wikidata and its contributors.
- We do **not** use the IMDb non-commercial datasets. Their terms don't allow republishing them as an online database of movie information.

### Inflation: U.S. Bureau of Labor Statistics
- **What:** Consumer Price Index for All Urban Consumers (CPI-U), U.S. city average, all items, not seasonally adjusted (series CUUR0000SA0).
- **Terms:** BLS data is in the public domain (https://www.bls.gov/opub/copyright-information.htm). Source: U.S. Bureau of Labor Statistics. BLS has not reviewed or endorsed our inflation-adjusted figures.

### Average ticket prices and pre-1982 totals: hand-curated
- **What:** annual average US ticket prices and lifetime totals for major pre-1982 films, transcribed from published sources. Each row in `data/manual/` cites its source (publication with date and page, or a URL).
- Years without a sourced ticket price are interpolated by the build and flagged as interpolated on the site.

## Our own calculations
Inflation-adjusted dollars, estimated admissions, all-time ranks "as of" a date, and career totals are BoxOfficeBozo's own calculations from the sources above. They're estimates, they may contain errors, and they are not official figures from any source. The site's About page explains the method.

## No warranty
The data is provided as is, without warranty of any kind, for entertainment and research.

## Takedown and correction requests
If you hold rights in material used here and want it removed, or you've spotted an error:
- Open an issue with the **Takedown or correction request** template: https://github.com/euskali/BoxOfficeBozo/issues/new?template=takedown.md
- Or contact the maintainer through their GitHub profile: https://github.com/euskali

We respond promptly. Accepted takedowns are removed from the repository and from the next site build, and the material is excluded from future builds. Formal copyright notices can also go to GitHub under its DMCA Takedown Policy (https://docs.github.com/en/site-policy/content-removal-policies/dmca-takedown-policy).

## Code license
The code is GPL-3.0. That license doesn't cover third-party data, which keeps its sources' terms.
