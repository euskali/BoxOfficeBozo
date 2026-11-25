"""M1 accept criteria, run against the real built tables.

PR CI has no data, so these skip there. The CI data build (build-data.yml) sets
BOFFO_REQUIRE_DATA=1, which turns a missing table into a failure.
"""

from __future__ import annotations

import json
import os
from datetime import date

import duckdb
import polars as pl
import pytest

from boffo_etl import paths
from boffo_etl.sample import is_sample_data
from boffo_etl.build import RELEASES_OUT_SCHEMA
from boffo_etl.manual import TITLE_ID_RE
from boffo_etl.sources.stat695 import SNAPSHOT_SCHEMA


def _require(path):
    if is_sample_data():  # make sample-data: fictional, so these real-data checks don't apply
        if os.environ.get("BOFFO_REQUIRE_DATA") == "1":
            pytest.fail("site/public/data holds sample data and BOFFO_REQUIRE_DATA=1")
        pytest.skip("site/public/data holds sample data (make sample-data)")
    if path.is_file():
        return path
    if os.environ.get("BOFFO_REQUIRE_DATA") == "1":
        pytest.fail(f"{path} is missing and BOFFO_REQUIRE_DATA=1")
    pytest.skip(f"{path.name} not built (data is built in CI)")


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(_require(paths.data_build() / "stat695_report.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def con():
    snaps = _require(paths.site_data() / "snapshots.parquet")
    rels = _require(paths.site_data() / "releases.parquet")
    c = duckdb.connect()
    for view, path in (("s", snaps), ("r", rels)):
        literal = "'" + str(path).replace("'", "''") + "'"
        c.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet({literal}) WHERE source = 'stat695'")
    yield c
    c.close()


def test_schemas():
    snaps = pl.read_parquet_schema(_require(paths.site_data() / "snapshots.parquet"))
    rels = pl.read_parquet_schema(_require(paths.site_data() / "releases.parquet"))
    assert dict(snaps) == SNAPSHOT_SCHEMA
    assert dict(rels) == RELEASES_OUT_SCHEMA  # with M3's match_method


def test_snapshot_count_matches_the_source(report, con):
    """Accept: every source row is a snapshot, or is counted as a duplicate or unkeyed row."""
    n = con.execute("SELECT count(*) FROM s").fetchone()[0]
    assert n == report["snapshot_rows"]
    assert n + report["exact_duplicates_dropped"] + report["unkeyed_rows"] == report["source_rows"]
    assert con.execute("SELECT count(*) FROM r").fetchone()[0] == report["releases"]


def test_no_weekend_has_duplicate_ranks(con):
    """Accept: no weekend has duplicate ranks."""
    dups = con.execute("""
        SELECT weekend_end, rank, count(*) FROM s WHERE rank IS NOT NULL
        GROUP BY ALL HAVING count(*) > 1 ORDER BY 1, 2 LIMIT 20""").fetchall()
    assert dups == []


def test_snapshot_keys_unique_and_linked(con):
    assert con.execute("""
        SELECT count(*) FROM (SELECT weekend_end, release_id FROM s GROUP BY ALL HAVING count(*) > 1)
    """).fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM s ANTI JOIN r USING (release_id)").fetchone()[0] == 0
    bad = [t for (t,) in con.execute("SELECT DISTINCT title_id FROM r").fetchall() if not TITLE_ID_RE.match(t)]
    assert bad == []


def test_coverage_spans_1982_to_2016(con):
    lo, hi = con.execute("SELECT min(weekend_end), max(weekend_end) FROM s").fetchone()
    assert lo.year == 1982
    assert hi >= date(2016, 12, 1)  # the docs say 1982-2016; the last chart may end in early 2017


def test_source_flags(con):
    assert con.execute("""
        SELECT count(*) FROM s WHERE is_estimate OR capture_url IS NOT NULL OR source <> 'stat695'
    """).fetchone()[0] == 0
