"""``make sample-data``: a small fictional dataset in site/public/data, for working on the site.

The ETL can't fetch locally, so without this a fresh clone has no data to run the site on. The
films, people and numbers here are made up (every title starts with "Sample:", every name is
a placeholder) and the manifest says ``"sample": true``: the site shows a banner, the data
tests skip, and ``make check`` fails, so sample data can't pass for the real thing. It is never
deployed: the data-build job builds the real tables from scratch. ``make pull-data`` copies the
real published tables instead.

Run with ``python -m boffo_etl.sample [--force]``. It won't overwrite real data without --force.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import date, datetime, timedelta, timezone

import polars as pl

from . import paths
from .build import RELEASES_OUT_SCHEMA, _table_entry
from .cume import CUME_SCHEMA, TICKET_SCHEMA
from .match import TITLE_SCHEMA
from .sources.cpi import SCHEMA as CPI_SCHEMA
from .sources.credits import CREDITS_SCHEMA, PEOPLE_SCHEMA
from .sources.stat695 import SNAPSHOT_SCHEMA

SEED = 1999
FIRST_SUNDAY = date(1982, 1, 3)
LAST_SUNDAY = date(2026, 11, 22)
BASELINE_DAY = date(1982, 1, 1)
FILMS = 260
RERELEASES = 12
DIRECTORS = 40
ACTORS = 120
SOURCE = "sample"
NOTE = "SAMPLE DATA: made up for local development (make sample-data)"

WORDS_A = ["Midnight", "Return of the", "Revenge of the", "Attack of the", "The Last", "Beyond the",
           "Curse of the", "Escape from the", "Night of the", "Rise of the", "Secret of the", "The Big"]
WORDS_B = ["Placeholder", "Lorem", "Ipsum", "Fixture", "Test Pattern", "Mock-Up", "Stand-In",
           "Dummy Text", "Prototype", "Rough Cut", "Understudy", "Stub"]
FIRST = ["Alex", "Sam", "Jo", "Robin", "Casey", "Dana", "Jesse", "Morgan", "Riley", "Taylor", "Quinn", "Avery"]
LAST = ["Lorem", "Ipsum", "Dolor", "Placeholder", "Testcase", "Mockwell", "Stubbs", "Fixture", "Sandbox",
        "Draft", "Example", "Specimen"]
STUDIOS = ["Sample Pictures", "Fictional Films", "Imaginary Studios", "Placeholder Bros."]
GENRES = ["Action", "Comedy", "Drama", "Horror", "Family", "Sci-Fi"]
RATINGS = ["G", "PG", "PG-13", "R"]


class SampleExistsError(Exception):
    """site/public/data holds real data; pass --force to replace it."""


def is_sample_data() -> bool:
    """True when site/public/data/manifest.json is `make sample-data` output."""
    manifest = paths.site_data() / "manifest.json"
    if not manifest.is_file():
        return False
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("sample") is True
    except (OSError, ValueError):
        return False


def _months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield date(y, m, 1)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _tables(rng: random.Random) -> dict[str, pl.DataFrame]:
    cpi = {m: round(94.0 * 1.028 ** ((m.year - 1982) + (m.month - 1) / 12), 3)
           for m in _months(date(1982, 1, 1), LAST_SUNDAY)}
    prices = {y: round(2.9 * 1.03 ** (y - 1982), 2) for y in range(1982, LAST_SUNDAY.year + 1)}

    people = [{"person_id": f"sample_d{i:03d}", "imdb_id": None,
               "name": f"{FIRST[i % len(FIRST)]} {LAST[(i * 5) % len(LAST)]} (director)"} for i in range(DIRECTORS)]
    people += [{"person_id": f"sample_a{i:03d}", "imdb_id": None,
                "name": f"{FIRST[(i * 7) % len(FIRST)]} {LAST[i % len(LAST)]} {i // len(LAST) + 1}"} for i in range(ACTORS)]

    titles, releases, credits, runs = [], [], [], []
    # Two films from before 1982 with sourced-looking (but made-up) baselines: one gross, one rentals.
    for n, (name, year, gross, rental) in enumerate([("Sample: Gone with the Placeholder", 1950, 150_000_000, False),
                                                     ("Sample: Rental Days", 1965, 40_000_000, True)]):
        tid = f"sample_old{n}"
        titles.append({"title_id": tid, "wikidata_qid": None, "title": name, "year": year, "release_date": None,
                       "distributor": STUDIOS[n], "genres": "Drama", "mpaa": "G",
                       "pre1982_baseline_gross": float(gross), "baseline_is_rental": rental, "baseline_source": NOTE})
        credits.append({"title_id": tid, "person_id": people[n]["person_id"], "role": "director", "billing": None,
                        "billing_source": None})
    for i in range(FILMS):
        tid = f"sample_{i:03d}"
        year = 1982 + i * (LAST_SUNDAY.year - 1982 + 1) // FILMS
        opened = date(year, 1, 1) + timedelta(days=rng.randrange(0, 330 if year == LAST_SUNDAY.year else 360))
        opened += timedelta(days=(4 - opened.weekday()) % 7)  # a Friday
        title = f"Sample: {rng.choice(WORDS_A)} {rng.choice(WORDS_B)}" + (f" {rng.choice(['II', 'III', 'Returns'])}" if i % 9 == 4 else "")
        studio = rng.choice(STUDIOS)
        titles.append({"title_id": tid, "wikidata_qid": None, "title": title, "year": year, "release_date": opened,
                       "distributor": studio, "genres": rng.choice(GENRES), "mpaa": rng.choice(RATINGS),
                       "pre1982_baseline_gross": None, "baseline_is_rental": None, "baseline_source": None})
        directors = rng.sample(range(DIRECTORS), 2 if i % 11 == 0 else 1)
        for d in directors:
            credits.append({"title_id": tid, "person_id": people[d]["person_id"], "role": "director", "billing": None,
                            "billing_source": None})
        for billing, a in enumerate(rng.sample(range(ACTORS), 6), start=1):
            credits.append({"title_id": tid, "person_id": people[DIRECTORS + a]["person_id"], "role": "actor",
                            "billing": billing, "billing_source": "statement_order"})
        runs.append((tid, f"sample:{tid}", None, title, studio, opened, rng.randint(4, 30),
                     min(150e6, rng.lognormvariate(15.8, 1.0)), rng.uniform(0.55, 0.8)))
    for i in rng.sample(range(FILMS), RERELEASES):
        tid, _, _, title, studio, opened, *_ = runs[i]
        again = opened + timedelta(days=7 * rng.randint(260, 1500))
        if again <= LAST_SUNDAY - timedelta(days=60):
            runs.append((tid, f"sample:{tid}:re", "Sample re-release", f"{title} (Re-release)", studio, again,
                         rng.randint(3, 6), rng.uniform(1e6, 8e6), rng.uniform(0.5, 0.7)))

    snapshots = []
    for tid, rid, label, title, studio, opened, weeks, first, decay in runs:
        sunday = opened + timedelta(days=(6 - opened.weekday()) % 7)
        total, theaters = 0, rng.randint(800, 4000)
        weekends = 0
        for w in range(weeks):
            day = sunday + timedelta(days=7 * w)
            if day > LAST_SUNDAY:
                break
            gross = int(first * decay ** w)
            total += gross
            weekends += 1
            snapshots.append({"weekend_end": day, "release_id": rid, "title_id": tid, "rank": None,
                              "weekend_gross": gross, "theaters": max(50, int(theaters * decay ** (w / 2))),
                              "total_gross": total, "weeks": w + 1, "source": SOURCE, "capture_url": None,
                              "is_estimate": False})
        if weekends:
            releases.append({"release_id": rid, "title_id": tid, "label": label, "release_date": opened,
                             "source_key": rid, "source": SOURCE, "title": title, "distributor": studio,
                             "genres": None, "mpaa": None, "first_weekend": sunday,
                             "last_weekend": sunday + timedelta(days=7 * (weekends - 1)), "weekends": weekends,
                             "is_rerelease": label is not None, "rerelease_reason": "sample" if label else None,
                             "parent_release_id": f"sample:{tid}" if label else None, "group_source": "auto",
                             "bom_release_id": None, "match_method": SOURCE})

    snaps = (pl.DataFrame(snapshots, schema=SNAPSHOT_SCHEMA)
             .with_columns(pl.col("weekend_gross").rank("ordinal", descending=True).over("weekend_end")
                           .cast(pl.Int32).alias("rank"))
             .sort("weekend_end", "rank"))

    # title_cume: each charted weekend's gross priced at its month's CPI and its year's ticket price.
    cume_rows = []
    baselines = {t["title_id"]: t for t in titles if t["pre1982_baseline_gross"] is not None}
    for t in baselines.values():
        g = t["pre1982_baseline_gross"]
        cume_rows.append({"title_id": t["title_id"], "as_of": BASELINE_DAY, "nominal": g,
                          "cpi": g * 100 / cpi[date(1982, 1, 1)], "admissions": g / prices[1982], "baseline": True})
    for r in snaps.iter_rows(named=True):
        g, day = r["weekend_gross"], r["weekend_end"]
        cume_rows.append({"title_id": r["title_id"], "as_of": day, "nominal": g,
                          "cpi": g * 100 / cpi[day.replace(day=1)],
                          "admissions": g / prices[day.year], "baseline": r["title_id"] in baselines})
    cume = (pl.DataFrame(cume_rows)
            .group_by("title_id", "as_of").agg(pl.col("nominal").sum(), pl.col("cpi").sum(),
                                               pl.col("admissions").sum(), pl.col("baseline").first())
            .sort("title_id", "as_of")
            .select("title_id", "as_of",
                    pl.col("nominal").cum_sum().over("title_id").cast(pl.Int64).alias("cume_nominal"),
                    pl.col("cpi").cum_sum().over("title_id").alias("cume_cpi"),
                    pl.col("admissions").cum_sum().over("title_id").alias("cume_admissions"),
                    "baseline")
            .sort("as_of", "title_id"))

    return {
        "snapshots": snaps,
        "releases": pl.DataFrame(releases, schema=RELEASES_OUT_SCHEMA),
        "titles": pl.DataFrame(titles, schema=TITLE_SCHEMA),
        "people": pl.DataFrame(people, schema=PEOPLE_SCHEMA),
        "credits": pl.DataFrame(credits, schema=CREDITS_SCHEMA),
        "cpi": pl.DataFrame([{"month": m, "cpi": v, "is_interpolated": False} for m, v in cpi.items()], schema=CPI_SCHEMA),
        "ticket_prices": pl.DataFrame([{"year": y, "avg_price": p, "source": NOTE, "is_interpolated": False}
                                       for y, p in prices.items()], schema=TICKET_SCHEMA),
        "title_cume": cume.select(list(CUME_SCHEMA)).cast(CUME_SCHEMA),
    }


def write(force: bool = False) -> list[dict]:
    """Writes the sample tables and a manifest marked sample into site/public/data."""
    out = paths.site_data()
    manifest = out / "manifest.json"
    if manifest.is_file() and not is_sample_data() and not force:
        raise SampleExistsError(f"{manifest} is real data; run with --force to replace it with sample data")
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, df in _tables(random.Random(SEED)).items():
        path = out / f"{name}.parquet"
        df.write_parquet(path)
        entries.append(_table_entry(path))
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": None,
        "sample": True,
        "tables": entries,
    }, indent=2) + "\n", encoding="utf-8")
    return entries


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        entries = write(force="--force" in args)
    except SampleExistsError as exc:
        print(f"sample-data: {exc}", file=sys.stderr)
        return 1
    for e in entries:
        print(f"sample-data: wrote {e['file']} ({e['rows']} rows)")
    print("sample-data: fictional films and made-up numbers, for local development only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
