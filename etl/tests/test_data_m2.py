"""M2 accept criteria, run against the real built tables.

PR CI has no data, so these skip there. The data-build job in deploy.yml sets
BOFFO_REQUIRE_DATA=1, which turns a missing table into a failure.

Accept: every weekend from 1982W01 through the latest completed weekend
exists, or is listed in the checks.py gap report as having no capture in
either archive. Carry-over films (e.g. late-2016 releases) have continuous
total_gross.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import date, timedelta

import duckdb
import pytest

from boffo_etl import paths
from boffo_etl.sample import is_sample_data
from boffo_etl.checks import GAP_REASONS
from boffo_etl.sources.bom_weekend import latest_completed_sunday


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
    return json.loads(_require(paths.data_build() / "bom_weekend_report.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def weekends() -> list[dict]:
    with _require(paths.data_build() / "bom_weekend_weekends.csv").open(newline="", encoding="utf-8") as fh:
        return [w for w in csv.DictReader(fh) if w["overlap"] != "true"]


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    for view, name in (("s", "snapshots"), ("r", "releases")):
        path = _require(paths.site_data() / f"{name}.parquet")
        literal = "'" + str(path).replace("'", "''") + "'"
        c.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet({literal})")
    yield c
    c.close()


def test_covers_through_the_latest_completed_weekend(report):
    as_of = date.fromisoformat(report["as_of"])
    assert report["latest_weekend_end"] == latest_completed_sunday(as_of).isoformat()
    assert report["first_weekend"] == "2017W01"


def test_every_weekend_is_charted_or_explained(con, report, weekends):
    """Accept: each Sunday since 1982W01 has a chart or a gap-report reason."""
    have = {d for (d,) in con.execute("""
        SELECT DISTINCT CAST(weekend_end - CAST(dayofweek(weekend_end) AS INTEGER) AS DATE) FROM s""").fetchall()}
    status = {w["weekend_end"]: w["status"] for w in weekends}
    end = date.fromisoformat(report["latest_weekend_end"])
    d, missing = date(1982, 1, 3), []
    while d <= end:
        if d not in have and status.get(d.isoformat()) not in GAP_REASONS:
            missing.append((d.isoformat(), status.get(d.isoformat(), "no entry")))
        d += timedelta(weeks=1)
    assert missing == []


def test_no_weekend_left_unfinished(weekends):
    unfinished = [(w["code"], w["status"], w["notes"][:100]) for w in weekends
                  if w["status"] not in ("ok", *GAP_REASONS)]
    assert unfinished == []


def test_carryovers_have_continuous_totals(con, report):
    """Accept: films charting on both sides of the 2016/2017 boundary keep one rising total_gross."""
    assert report["unlinked_carryovers"] == []
    boundary = date.fromisoformat(report["boundary_weekend"])
    pairs = con.execute("""
        WITH before AS (SELECT release_id, arg_max(total_gross, weekend_end) AS tg FROM s
                        WHERE weekend_end <= ? AND weekend_end > ? - INTERVAL 28 DAY GROUP BY 1),
             after AS (SELECT release_id, arg_min(total_gross, weekend_end) AS tg FROM s
                       WHERE weekend_end > ? AND weekend_end <= ? + INTERVAL 28 DAY GROUP BY 1)
        SELECT release_id, before.tg, after.tg FROM before JOIN after USING (release_id)""",
                        [boundary, boundary, boundary, boundary]).fetchall()
    assert len(pairs) >= 30  # dozens of late-2016 films carried into January 2017
    assert [p for p in pairs if p[1] is not None and p[2] is not None and p[2] < p[1]] == []


def test_new_rows_trace_to_an_archive_capture(con, report):
    boundary = date.fromisoformat(report["boundary_weekend"])
    bad = con.execute("""
        SELECT count(*) FROM s WHERE weekend_end > ?
          AND (source NOT IN ('wayback', 'commoncrawl') OR capture_url IS NULL
               OR NOT (capture_url LIKE 'https://web.archive.org/web/%'
                       OR capture_url LIKE 'https://data.commoncrawl.org/%'))""", [boundary]).fetchone()[0]
    assert bad == 0
    assert con.execute("SELECT count(*) FROM s WHERE weekend_end <= ? AND source <> 'stat695'",
                       [boundary]).fetchone()[0] == 0


def test_rl_ids_are_unique_to_a_release(con):
    assert con.execute("""
        SELECT count(*) FROM (SELECT bom_release_id FROM r WHERE bom_release_id IS NOT NULL
                              GROUP BY 1 HAVING count(*) > 1)""").fetchone()[0] == 0


def test_no_weekend_has_duplicate_ranks_after_2016(con, report):
    boundary = date.fromisoformat(report["boundary_weekend"])
    assert con.execute("""
        SELECT count(*) FROM (SELECT weekend_end, rank FROM s WHERE weekend_end > ? AND rank IS NOT NULL
                              GROUP BY ALL HAVING count(*) > 1)""", [boundary]).fetchone()[0] == 0
