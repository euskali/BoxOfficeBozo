from __future__ import annotations

import json
from datetime import date, timedelta

import polars as pl
import pytest

from boffo_etl import checks
from boffo_etl.sources.stat695 import RELEASE_SCHEMA, SNAPSHOT_SCHEMA


def test_clean_repo_exits_zero(repo, capsys):
    assert checks.main([]) == 0
    assert "no built tables yet (data is built in CI)" in capsys.readouterr().out


def test_invalid_manual_csv_exits_one(repo, capsys):
    (repo / "data" / "manual" / "ticket_prices.csv").write_text(
        "year,avg_price_usd,source,source_url,notes\n1990,4.2,TODO,,\n", encoding="utf-8"
    )
    assert checks.main([]) == 1
    assert "placeholder" in capsys.readouterr().out


def test_lists_parquet_row_counts(repo, capsys):
    out = repo / "data" / "build"
    out.mkdir(parents=True)
    pl.DataFrame({"a": [1, 2, 3]}).write_parquet(out / "t.parquet")
    assert checks.main([]) == 0
    assert "t.parquet: 3 rows" in capsys.readouterr().out


# --- snapshots / releases ----------------------------------------------------

SUN = date(1990, 1, 7)  # a Sunday


def snap(week: int, release: str, rank: int, total: int, weekend: int = 100, end: date | None = None) -> dict:
    return {
        "weekend_end": end or SUN + timedelta(weeks=week), "release_id": f"legacy:{release}",
        "title_id": f"bb_{release}", "rank": rank, "weekend_gross": weekend, "theaters": 10,
        "total_gross": total, "weeks": week + 1, "source": "stat695", "capture_url": None, "is_estimate": False,
    }


def write_tables(repo, snaps: list[dict], releases: list[str] | None = None) -> None:
    site = repo / "site" / "public" / "data"
    site.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(snaps, schema=SNAPSHOT_SCHEMA).write_parquet(site / "snapshots.parquet")
    ids = releases if releases is not None else sorted({s["release_id"].split(":")[1] for s in snaps})
    pl.DataFrame(
        [{"release_id": f"legacy:{r}", "title_id": f"bb_{r}", "source_key": r, "source": "stat695",
          "is_rerelease": False, "group_source": "auto"} for r in ids],
        schema=RELEASE_SCHEMA,
    ).write_parquet(site / "releases.parquet")


def run(capsys) -> tuple[int, str]:
    code = checks.main([])
    return code, capsys.readouterr().out


CLEAN = [snap(0, "a", 1, 100), snap(0, "b", 2, 50, weekend=50), snap(1, "a", 1, 200), snap(1, "b", 2, 80, weekend=30)]


def test_clean_snapshots_pass(repo, capsys):
    write_tables(repo, CLEAN)
    code, out = run(capsys)
    assert code == 0, out
    assert "snapshots: 2 weekends from 1990-01-07 to 1990-01-14, 0 missing" in out
    assert "0 error(s), 0 warning(s)" in out


def test_duplicate_ranks_are_errors(repo, capsys):
    write_tables(repo, CLEAN + [snap(1, "c", 2, 10, weekend=10)])
    code, out = run(capsys)
    assert code == 1
    assert "1 weekends have duplicate ranks" in out and "1990-01-14 rank 2: legacy:b, legacy:c" in out


def test_duplicate_keys_are_errors(repo, capsys):
    write_tables(repo, CLEAN + [snap(1, "a", 3, 200)])
    code, out = run(capsys)
    assert code == 1 and "(weekend_end, release_id) pairs appear more than once" in out


def test_decreasing_totals_are_warnings(repo, capsys):
    write_tables(repo, CLEAN + [snap(2, "a", 1, 150)])
    code, out = run(capsys)
    assert code == 0
    assert "total_gross goes down 1 times in 1 releases (flagged, not fixed)" in out
    assert "legacy:a 1990-01-21: 200 -> 150" in out


def test_total_below_weekend_warns(repo, capsys):
    write_tables(repo, [snap(0, "a", 1, 50, weekend=100)])
    code, out = run(capsys)
    assert code == 0 and "total_gross below weekend_gross" in out


def test_gaps_and_non_sunday_weekends(repo, capsys):
    rows = [
        snap(0, "a", 1, 100),
        snap(3, "a", 1, 300),  # weeks 1 and 2 missing
        snap(0, "b", 1, 100, end=SUN + timedelta(weeks=4, days=1)),  # holiday Monday counts for its Sunday
        snap(0, "b", 1, 200, end=SUN + timedelta(weeks=5)),
    ]
    write_tables(repo, rows)
    code, out = run(capsys)
    assert code == 1  # M2 accept: a missing weekend needs a gap-report reason
    assert "2 weekends are missing without a gap-report reason" in out
    assert "weekend ending 1990-01-14 (no entry); weekend ending 1990-01-21 (no entry)" in out
    assert "1 weekends don't end on a Sunday, e.g. 1990-02-05 (Monday)" in out


def write_bom(repo, weekends: list[tuple], **report) -> None:
    build = repo / "data" / "build"
    build.mkdir(parents=True, exist_ok=True)
    lines = ["code,weekend_end,status,archive,style,capture_url,rows,unkeyed_rows,overlap,notes"]
    lines += [f"{c},{d},{st},,,,0,0,{'true' if ov else 'false'},{note}" for c, d, st, ov, note in weekends]
    (build / "bom_weekend_weekends.csv").write_text("".join(x + chr(10) for x in lines), encoding="utf-8")
    main = [w for w in weekends if not w[3]]
    base = {"weekends": len(main), "first_weekend": main[0][0], "latest_weekend": main[-1][0],
            "latest_weekend_end": weekends[-1][1], "as_of": "1990-02-20", "statuses": {}, "archives": {},
            "styles": {}, "snapshot_rows": 0, "estimate_rows": 0, "links": {}, "release_pages": {},
            "unlinked_carryovers": [], "link_conflicts": [], "unkeyed_rows": 0}
    (build / "bom_weekend_report.json").write_text(json.dumps({**base, **report}), encoding="utf-8")


def test_gap_report_explains_missing_weekends(repo, capsys):
    write_tables(repo, [snap(0, "a", 1, 100), snap(2, "a", 1, 300)])
    write_bom(repo, [("1990W02", "1990-01-14", "ok", False, ""), ("1990W03", "1990-01-21", "ok", False, ""),
                     ("1990W04", "1990-01-28", "no_capture", False, ""),
                     ("1990W05", "1990-02-04", "empty_chart", False, "")],
              latest_weekend_end="1990-02-04")
    code, out = run(capsys)
    assert "1 weekends are missing without a gap-report reason, e.g. weekend ending 1990-01-14 (ok)" in out
    assert "no capture in either archive (Wayback Machine, Common Crawl): e.g. 1990W04 (ending 1990-01-28)" in out
    assert "archived chart lists no films: e.g. 1990W05 (ending 1990-02-04)" in out
    assert code == 1


def test_gap_report_covers_through_the_latest_weekend(repo, capsys):
    write_tables(repo, [snap(w, "a", 1, 100 * (w + 1)) for w in range(3)])
    write_bom(repo, [("1990W02", "1990-01-14", "ok", False, ""), ("1990W03", "1990-01-21", "ok", False, ""),
                     ("1990W04", "1990-01-28", "no_capture", False, "")])
    code, out = run(capsys)
    assert code == 0, out
    assert "(latest completed weekend 1990-01-28), 1 missing" in out


def test_bom_report_errors_and_warnings(repo, capsys):
    write_tables(repo, [snap(w, "a", 1, 100 * (w + 1)) for w in range(4)])
    write_bom(repo, [("1989W52", "1989-12-31", "no_capture", True, ""),
                     ("1990W02", "1990-01-14", "error", False, "wayback lookup failed: HTTP 503"),
                     ("1990W03", "1990-01-21", "pending", False, "fetch time budget used up"),
                     ("1990W04", "1990-01-28", "unchecked", False, "")],
              unlinked_carryovers=[{"bom_release_id": "rl1", "title": "Holdover", "weeks": 3, "total_gross": 9}],
              link_conflicts=["rl2: tied between legacy:x and legacy:y"])
    code, out = run(capsys)
    assert code == 1
    assert "1 weekends: archive lookup failed (retried next run), e.g. 1990W02 (wayback lookup failed" in out
    assert "1 weekends: not fetched yet" in out and "1 weekends: not in the Wayback Machine" in out
    assert "1 stat695 weekends couldn't be re-read for stitching" in out
    assert "1 films charting on 1990W02 were already in release" in out and "rl1 'Holdover' (week 3)" in out
    assert "1 stitching conflicts left unlinked" in out


def test_release_integrity_errors(repo, capsys):
    write_tables(repo, CLEAN, releases=["a", "a", "BAD"])
    code, out = run(capsys)
    assert code == 1
    assert "1 release_ids appear more than once" in out
    assert "invalid title_id" in out and "bb_BAD" in out
    assert "snapshot release_ids are missing from releases, e.g. legacy:b" in out


def test_title_grouping_two_first_releases_warns(repo, capsys):
    write_tables(repo, CLEAN)
    site = repo / "site" / "public" / "data"
    base = {"source_key": "x", "group_source": "auto"}
    pl.DataFrame([
        {**base, "release_id": "legacy:a", "title_id": "bb_a", "title": "Space Saga", "source": "stat695",
         "is_rerelease": False, "first_weekend": SUN},
        {**base, "release_id": "legacy:b", "title_id": "bb_b", "title": "Holdover", "source": "stat695",
         "is_rerelease": False, "first_weekend": SUN},
        # Joined to "Space Saga" as if it were the same film, but it's a first release.
        {**base, "release_id": "bom:rl1", "title_id": "bb_a", "title": "Space Saga II", "source": "bom_weekend",
         "is_rerelease": False, "first_weekend": SUN + timedelta(weeks=60)},
        # A labelled re-release in a title's group is expected.
        {**base, "release_id": "bom:rl2", "title_id": "bb_b", "title": "Holdover", "source": "bom_weekend",
         "is_rerelease": True, "first_weekend": SUN + timedelta(weeks=70)},
    ], schema=RELEASE_SCHEMA).write_parquet(site / "releases.parquet")
    code, out = run(capsys)
    assert code == 0, out
    assert ("1 title_ids group more than one first release (check the grouping), "
            "e.g. bb_a: Space Saga (legacy:a); Space Saga II (bom:rl1)") in out
    assert "0 error(s), 1 warning(s)" in out


# --- stat695 report ------------------------------------------------------------

def report(**kw) -> dict:
    base = {
        "source_rows": 10, "source_releases": 3, "documented_rows": 10, "documented_releases": 3,
        "snapshot_rows": 8, "exact_duplicates_dropped": 1, "unkeyed_rows": 1,
        "unkeyed_examples": [{"_row": 4, "movie_id": "x", "weekend_end": None}],
        "duplicate_chart_labels": [{"chart": "1989W53", "same_as": "1990W01", "rows": 1}],
        "releases": 3, "weekends": 2, "weekend_min": "1990-01-07", "weekend_max": "1990-01-14",
        "nonintegral_values": {}, "nulls": {}, "releases_missing_release_date": 0,
        "releases_with_varying": {}, "rereleases": {}, "manual_groups_applied": 0,
    }
    base.update(kw)
    return base


def write_report(repo, r: dict) -> None:
    build = repo / "data" / "build"
    build.mkdir(parents=True, exist_ok=True)
    (build / "stat695_report.json").write_text(json.dumps(r), encoding="utf-8")


def test_report_flags_source_anomalies(repo, capsys):
    write_report(repo, report())
    code, out = run(capsys)
    assert code == 0
    assert "1 source rows exactly repeat another row" in out and "1989W53 repeats 1990W01" in out
    assert "1 source rows have no end_date or movie_id" in out


@pytest.mark.parametrize("kw, message", [
    ({"snapshot_rows": 9}, "row counts don't reconcile"),
])
def test_report_reconciliation_errors(repo, capsys, kw, message):
    write_report(repo, report(**kw))
    code, out = run(capsys)
    assert code == 1 and message in out


def test_report_documented_counts_warn(repo, capsys):
    write_report(repo, report(documented_rows=11))
    code, out = run(capsys)
    assert code == 0 and "its docs say 11" in out


def test_report_row_count_must_match_parquet(repo, capsys):
    write_report(repo, report())
    pl.DataFrame({"a": [1, 2]}).write_parquet(repo / "data" / "build" / "stat695_snapshots.parquet")
    code, out = run(capsys)
    assert code == 1 and "stat695_snapshots.parquet has 2 rows, the report says 8" in out


def test_report_warns_on_encoding_fallback(repo, capsys):
    write_report(repo, report(unmarked_string_encoding="WINDOWS-1252"))
    code, out = run(capsys)
    assert code == 0 and "read as WINDOWS-1252" in out
