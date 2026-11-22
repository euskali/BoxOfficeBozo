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
    assert ("1 title_ids group more than one first release (check the grouping or the match), biggest first, "
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


# --- M3: matching ------------------------------------------------------------------

def match_report(**kw) -> dict:
    base = {
        "films_loaded": 100, "releases": 3, "titles": 2, "gross_total": 100, "gross_matched_tt": 98,
        "matched_share": 0.98, "matched_target": 0.97, "top_releases": 1000, "top_unmatched": [],
        "by_method": {"p1237": {"releases": 2, "gross": 98, "share": 0.98},
                      "unmatched": {"releases": 1, "gross": 2, "share": 0.02}},
        "ambiguous_count": 0, "ambiguous": [], "notes": {},
    }
    base.update(kw)
    return base


def write_build_json(repo, name: str, data: dict) -> None:
    build = repo / "data" / "build"
    build.mkdir(parents=True, exist_ok=True)
    (build / name).write_text(json.dumps(data), encoding="utf-8")


def test_match_report_meeting_the_targets_passes(repo, capsys):
    write_build_json(repo, "match_report.json", match_report())
    code, out = run(capsys)
    assert code == 0, out
    assert "match: 3 releases -> 2 titles, 98.00% of gross matched to an IMDb id; p1237 2 (98.0% of gross)" in out


@pytest.mark.parametrize("kw, message", [
    ({"matched_share": 0.9}, "only 90.00% of nominal gross is matched to an IMDb id (accept: at least 97%)"),
    ({"top_unmatched": [{"release_id": "legacy:x", "title": "X", "gross": 5, "method": "unmatched"}]},
     "1 of the top 1000 releases by gross have no IMDb id"),
    ({"films_loaded": 0}, "no Wikidata snapshot was loaded"),
])
def test_match_report_errors(repo, capsys, kw, message):
    write_build_json(repo, "match_report.json", match_report(**kw))
    code, out = run(capsys)
    assert code == 1 and message in out


def test_match_and_wikidata_notes_warn(repo, capsys):
    write_build_json(repo, "match_report.json", match_report(
        notes={"group_conflicts": {"count": 1, "examples": ["group bb_x: a -> tt1, b -> tt2"]}}))
    write_build_json(repo, "wikidata_report.json", {
        "snapshot": "2026-10", "endpoint": "https://qlever.dev/api/wikidata", "items": 5, "items_with_tt": 4,
        "bom_ids": 3, "items_with_bom_id": 3, "stale_reason": "HTTP 503",
        "bom_ids_on_several_items": ["dup: Q1, Q2"], "release_page_tt_lookup": {"asked": 1, "found": 0, "error": None}})
    code, out = run(capsys)
    assert code == 0, out
    assert "1 groups whose releases matched different titles" in out
    assert "so 2026-10's was used (HTTP 503)" in out and "dup: Q1, Q2" in out


def write_titles(repo, rows: list[dict]) -> None:
    from boffo_etl.match import TITLE_SCHEMA

    pl.DataFrame(rows, schema=TITLE_SCHEMA).write_parquet(repo / "site" / "public" / "data" / "titles.parquet")


def test_titles_cover_every_release(repo, capsys):
    write_tables(repo, CLEAN)
    write_titles(repo, [{"title_id": "bb_a"}, {"title_id": "bb_b"}])
    code, out = run(capsys)
    assert code == 0, out
    write_titles(repo, [{"title_id": "bb_a"}, {"title_id": "tt0000001"}, {"title_id": "tt0000001"},
                        {"title_id": "bb_c", "pre1982_baseline_gross": 1.0}])
    code, out = run(capsys)
    assert code == 1
    assert "1 title_ids appear more than once, e.g. tt0000001" in out
    assert "1 release title_ids are missing from titles, e.g. bb_b" in out
    assert "1 titles have neither a release nor a baseline, e.g. tt0000001" in out
    assert "titles with an IMDb id have no Wikidata item" in out


# --- M4: credits -------------------------------------------------------------------

def credits_report(**kw) -> dict:
    r = {"month": "2026-11", "month_complete": True, "fetch": {"planned": 2, "done": 2, "stopped": None},
         "films": 2, "films_with_statements": 2, "films_from_older_month": 0, "films_without_statements": 0,
         "films_without_statements_examples": [], "items_missing_on_wikidata": [], "voice_cast_films": 1,
         "credits": 6, "director_credits": 2, "actor_credits": 4,
         "billing_source": {"p1545": 0, "statement_order": 4}, "people": 5, "people_with_imdb_id": 2,
         "people_without_name": 0, "people_without_name_examples": [], "top_billed": 4,
         "films_with_director": 2, "films_with_director_share": 1.0, "films_with_top_billed_cast": 1,
         "films_with_top_billed_cast_share": 0.5, "top_titles": 1000, "top_without_director": [],
         "top_without_statements": 0}
    return {**r, **kw}


def write_credits(repo, credits: list[tuple], people: list[tuple]) -> None:
    from boffo_etl.sources.credits import CREDITS_SCHEMA, PEOPLE_SCHEMA

    site = repo / "site" / "public" / "data"
    site.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(credits, schema=CREDITS_SCHEMA, orient="row").write_parquet(site / "credits.parquet")
    pl.DataFrame(people, schema=PEOPLE_SCHEMA, orient="row").write_parquet(site / "people.parquet")


GOOD_CREDITS = [("tt0000001", "Q1", "director", None, None), ("tt0000001", "Q2", "actor", 1, "statement_order"),
                ("tt0000001", "Q3", "actor", 2, "p1545")]
GOOD_PEOPLE = [("Q1", "nm0000229", "Steven Spielberg"), ("Q2", None, "A"), ("Q3", None, "B")]


def test_clean_credits_pass(repo, capsys):
    write_build_json(repo, "credits_report.json", credits_report())
    write_credits(repo, GOOD_CREDITS, GOOD_PEOPLE)
    code, out = run(capsys)
    assert code == 0, out
    assert "credits: month 2026-11: statements for 2 of 2 films; 6 credits (2 director, 4 actor" in out
    assert "100.0% of films have a director, 50.0% at least 4 cast; 1 films have a voice cast" in out


def test_credit_integrity_errors(repo, capsys):
    write_credits(repo, [*GOOD_CREDITS, ("tt0000001", "Q2", "actor", 1, "statement_order"),
                         ("tt0000001", "Q4", "director", 3, None), ("tt0000001", "Q5", "actor", 7, "guess"),
                         ("tt0000001", "Q6", "producer", None, None)],
                  [*GOOD_PEOPLE, ("Q4", "tt1", "D"), ("Q4", None, "D"), ("Q5", None, "E")])
    write_titles(repo, [{"title_id": "tt0000002"}])
    code, out = run(capsys)
    assert code == 1
    for message in ("1 credits appear more than once, e.g. tt0000001 Q2 actor", "unknown roles: ['producer']",
                    "2 credits have a billing that doesn't fit their role",
                    "1 films' billing isn't 1..n, e.g. tt0000001",
                    "1 credited title_ids are not in titles, e.g. tt0000001",
                    "1 credited people are missing, e.g. Q6", "1 person_ids appear more than once, e.g. Q4",
                    "people have malformed ids, e.g. Q4 tt1"):
        assert message in out, message


def test_credit_coverage_warnings(repo, capsys):
    write_build_json(repo, "credits_report.json", credits_report(
        month_complete=False, fetch={"planned": 9, "done": 3, "stopped": "time budget"},
        films_without_statements=6, top_without_statements=1,
        films_without_statements_examples=[{"title_id": "tt0000009", "title": "Late", "gross": 5}],
        top_without_director=[{"title_id": "tt0000005", "title": "No Director", "gross": 1_000_000}],
        people_without_name=1, people_without_name_examples=["Q77"]))
    code, out = run(capsys)
    assert code == 0, out
    assert "(incomplete)" in out
    assert "6 films have no Wikidata statements fetched yet (1 of the top 1000; fetch time budget)" in out
    assert "1 of the top 1000 films by gross have no director on Wikidata (P57), e.g. tt0000005 'No Director'" in out
    assert "1 credited people have no English or mul label, e.g. Q77" in out


# --- M5 ---------------------------------------------------------------------------

def write_m5(repo, *, cpi_rows=None, tickets=None, cume_rows=None, report=None, cpi_report=None) -> None:
    """The M5 tables and reports for CLEAN, built by cume.build unless given."""
    from boffo_etl import cume

    write_tables(repo, CLEAN)
    write_titles(repo, [{"title_id": "bb_a"}, {"title_id": "bb_b"}])
    site, build_dir = repo / "site/public/data", repo / "data/build"
    build_dir.mkdir(parents=True, exist_ok=True)
    months = [date(1913 + i // 12, i % 12 + 1, 1) for i in range((1990 - 1913) * 12 + 2)]
    cpi = pl.DataFrame({"month": months, "cpi": [100.0] * len(months)}, schema=cume.cpi_source.SCHEMA)
    b = cume.build(pl.read_parquet(site / "snapshots.parquet"), pl.read_parquet(site / "releases.parquet"),
                   pl.read_parquet(site / "titles.parquet"), cpi,
                   [{"year": 1989, "avg_price_usd": 4.0, "source": "NATO table", "source_url": ""}])
    (pl.DataFrame(cpi_rows, schema=cume.cpi_source.SCHEMA, orient="row") if cpi_rows is not None else b.cpi) \
        .write_parquet(site / "cpi.parquet")
    (pl.DataFrame(tickets, schema=cume.TICKET_SCHEMA, orient="row") if tickets is not None else b.tickets) \
        .write_parquet(site / "ticket_prices.parquet")
    (pl.DataFrame(cume_rows, schema=cume.CUME_SCHEMA, orient="row") if cume_rows is not None else b.cume) \
        .write_parquet(site / "title_cume.parquet")
    (build_dir / "cume_report.json").write_text(json.dumps(b.report | (report or {}), default=str))
    cr = {"series": "CUUR0000SA0", "base": "1982-84=100", "built_on": "1990-03-20", "months": len(months),
          "first_month": "1913-01-01", "latest_month": "1990-02-01", "latest_cpi": 100.0, "windows": 8,
          "fetched": [], "fetch": {"stopped": None}, "stale_windows": [], "pruned_cache_entries": 0,
          "network_requests": 0}
    (build_dir / "cpi_report.json").write_text(json.dumps(cr | (cpi_report or {})))


def test_clean_m5_tables_pass(repo, capsys):
    write_m5(repo)
    code, out = run(capsys)
    assert code == 0, out
    assert "cpi: BLS CUUR0000SA0 (1982-84=100) 1913-01-01 to 1990-02-01" in out
    assert "title_cume: 2 titles, 4 rows" in out
    assert "carried forward" in out  # 1990 uses 1989's price


def test_m5_table_errors(repo, capsys):
    write_m5(repo, cpi_rows=[(date(1913, 1, 1), 9.8), (date(1913, 3, 1), 0.0), (date(1913, 3, 1), 9.9)],
             tickets=[(1989, 4.0, "NATO table", False), (1990, 4.0, "NATO table", True), (1992, 4.1, "x", False)],
             cume_rows=[("bb_a", SUN, 100, 100.0, 25.0, False), ("bb_a", SUN, 100, 100.0, 25.0, False),
                        ("bb_x", SUN, -5, -5.0, -1.0, False)])
    code, out = run(capsys)
    assert code == 1
    for message in ("1 months appear more than once", "1 months are missing between 1913-01-01 and 1913-03-01",
                    "1 months have no positive index", "years 1989-1992 aren't each there once (3 rows)",
                    "1 years' is_interpolated doesn't match their source",
                    "1 (title_id, as_of) pairs appear more than once, e.g. bb_a 1990-01-07",
                    "1 title_ids are not in titles, e.g. bb_x", "1 charted titles have no rows, e.g. bb_b",
                    "final totals add up to $95, not the releases' latest totals plus baselines less what late "
                    "runs repeat ($280)", "1 rows have a negative total, e.g. bb_x 1990-01-07 -5"):
        assert message in out, message


def test_m5_report_warnings(repo, capsys):
    write_m5(repo, report={"ticket_years_interpolated": [2020, 2021], "deltas_after_latest_cpi": 2,
                           "gross_after_latest_cpi": 1500, "titles_without_admissions": 1,
                           "titles_without_admissions_examples": ["tt0031381"], "releases_without_totals": 1,
                           "releases_without_totals_examples": [{"release_id": "legacy:venom", "title": "Venom"}],
                           "overlaps": [{"release_id": "bom:rl1", "title": "Jaws", "kind": "late_run",
                                         "opened": "1975-06-22", "excess": 254, "covered": 0}]},
             cpi_report={"stale_windows": ["1983-1992 (1990-W10)"], "fetch": {"stopped": "fetching disabled"},
                         "built_on": "1990-06-30"})
    code, out = run(capsys)
    assert code == 0, out
    for message in ("CPI answers from an earlier week are used for 1983-1992 (1990-W10) (this week's request: "
                    "fetching disabled)", "the latest CPI month is 1990-02, 149 days before the build",
                    "ticket prices for 1990-1990 are carried forward",
                    "2 years' ticket prices are interpolated between sourced years (no figure found yet): 2020, 2021",
                    "2 weekly changes ($1,500) are after the latest CPI month (1990-02)",
                    "1 late runs or carry-ins brought earlier money", "bom:rl1 'Jaws': $254 from 1975-06-22",
                    "1 titles have no admissions (a year with no ticket price), e.g. tt0031381",
                    "1 releases charted without a total gross on any weekend, so they add nothing to their "
                    "titles' totals, e.g. legacy:venom 'Venom'"):
        assert message in out, message
