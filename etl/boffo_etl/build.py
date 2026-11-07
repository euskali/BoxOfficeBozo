"""Build orchestrator. Run with ``python -m boffo_etl.build``."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import polars as pl

from . import match, paths
from .fetch import FetchDisabledError
from .manual import validate_manual_dir
from .sources import bom_weekend, stat695, wikidata

REQUIRE_DATA_FLAG = "BOFFO_REQUIRE_DATA"

# Source steps: (name, milestone, callable or None if not implemented yet).
# Each step writes its per-source tables to data/build/.
STEPS: list[tuple[str, str, Callable[[], object] | None]] = [
    ("stat695", "M1", stat695.run),
    ("bom_weekend", "M2", bom_weekend.run),
    ("wikidata", "M3", wikidata.run),
    ("cpi", "M5", None),
]

# Shipped tables and the per-source parts in data/build/ they are combined from.
SNAPSHOT_SOURCES = ("stat695", "bom_weekend")
PUBLISHED = ("snapshots", "releases", "titles")

# releases.parquet as shipped: the per-source columns plus the new-site release id (rl...),
# for stat695 releases too when M2 stitched a carry-over film to one.
PUBLISHED_RELEASE_SCHEMA = {**stat695.RELEASE_SCHEMA, "bom_release_id": pl.String}
# ...plus how M3 matched each release to its title (match.METHODS).
RELEASES_OUT_SCHEMA = {**PUBLISHED_RELEASE_SCHEMA, "match_method": pl.String}


def _table_entry(path: Path) -> dict:
    data = path.read_bytes()
    return {
        "name": path.stem,
        "file": path.name,
        "rows": pl.scan_parquet(path).select(pl.len()).collect().item(),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def assemble_releases(releases: pl.DataFrame, snapshots: pl.DataFrame, links: pl.DataFrame | None) -> pl.DataFrame:
    """Add bom_release_id and recount each release's weekends across all sources.

    A stat695 release that M2 stitched to an rl release keeps charting after
    2016, so its first/last weekend and weekend count come from every snapshot.
    """
    # Only new-site keys are rl ids; an old-style 2017-2019 page keys by legacy id.
    own = pl.when((pl.col("source") == bom_weekend.SOURCE) & pl.col("source_key").str.starts_with("rl"))         .then(pl.col("source_key"))
    out = releases.with_columns(own.alias("bom_release_id"))
    if links is not None and links.height:
        out = out.join(links.select("release_id", pl.col("bom_release_id").alias("_linked")),
                       on="release_id", how="left").with_columns(
            pl.coalesce("bom_release_id", "_linked").alias("bom_release_id")).drop("_linked")
    spans = snapshots.group_by("release_id").agg(
        pl.col("weekend_end").min().alias("_first"), pl.col("weekend_end").max().alias("_last"),
        pl.col("weekend_end").n_unique().cast(pl.Int32).alias("_n"))
    out = (out.join(spans, on="release_id", how="left")
           .with_columns(pl.coalesce("_first", "first_weekend").alias("first_weekend"),
                         pl.coalesce("_last", "last_weekend").alias("last_weekend"),
                         pl.coalesce("_n", "weekends").alias("weekends"))
           .drop("_first", "_last", "_n"))
    return out.select(list(PUBLISHED_RELEASE_SCHEMA)).cast(PUBLISHED_RELEASE_SCHEMA).sort("first_weekend", "release_id")


def _parts(table: str) -> list[pl.DataFrame]:
    files = [paths.data_build() / f"{src}_{table}.parquet" for src in SNAPSHOT_SOURCES]
    return [pl.read_parquet(p) for p in files if p.is_file()]


def publish_tables() -> list[dict]:
    """Combine per-source parts, match releases to titles (M3), write site/public/data/<table>.parquet."""
    snaps = _parts("snapshots")
    rels = _parts("releases")
    if not snaps and not rels:
        return []
    snapshots = (pl.concat(snaps, how="diagonal_relaxed").sort("weekend_end", "rank", "release_id", nulls_last=True)
                 if snaps else pl.DataFrame(schema=stat695.SNAPSHOT_SCHEMA))
    outputs: dict[str, pl.DataFrame] = {"snapshots": snapshots}
    if rels:
        links_path = paths.data_build() / "bom_weekend_links.parquet"
        links = pl.read_parquet(links_path) if links_path.is_file() else None
        releases = assemble_releases(pl.concat(rels, how="diagonal_relaxed"), snapshots, links)
        matched = match.apply(releases, snapshots)
        outputs = {"snapshots": matched.snapshots, "releases": matched.releases.select(list(RELEASES_OUT_SCHEMA)),
                   "titles": matched.titles}
    tables = []
    for name in PUBLISHED:
        if name in outputs:
            out = paths.site_data() / f"{name}.parquet"
            outputs[name].write_parquet(out)
            tables.append(_table_entry(out))
    return tables


def write_manifest(tables: list | None = None) -> None:
    manifest = {
        "schema_version": 1,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": os.environ.get("GITHUB_SHA") or None,
        "tables": tables or [],
    }
    out = paths.site_data() / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    for d in (paths.data_raw(), paths.data_build(), paths.site_data()):
        d.mkdir(parents=True, exist_ok=True)

    issues = validate_manual_dir(paths.data_manual())
    for issue in issues:
        print(issue)
    if any(i.severity == "error" for i in issues):
        print("build aborted: fix manual CSV errors first", file=sys.stderr)
        return 1

    fetch_on = os.environ.get("BOFFO_FETCH") == "1"
    require = os.environ.get(REQUIRE_DATA_FLAG) == "1"
    print(f"network fetching: {'ENABLED (BOFFO_FETCH=1)' if fetch_on else 'disabled (set BOFFO_FETCH=1 in CI to enable)'}")

    for name, milestone, step in STEPS:
        if step is None:
            print(f"step {name}: skipped, not implemented until {milestone}")
            continue
        print(f"step {name}: running")
        try:
            step()
        except FetchDisabledError as exc:
            if require:
                print(f"step {name}: FAILED, {REQUIRE_DATA_FLAG}=1 and {exc}", file=sys.stderr)
                return 1
            print(f"step {name}: skipped, its raw input is not cached in data/raw/ (data is fetched in CI)")

    tables = publish_tables()
    for t in tables:
        print(f"published {t['file']}: {t['rows']} rows")
    write_manifest(tables)
    print(f"wrote {paths.site_data() / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
