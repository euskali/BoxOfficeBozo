"""Data-quality report. Run with ``python -m boffo_etl.checks``; exits 1 on any error.

Severity rule: an *error* means the pipeline produced something broken (counts
that don't reconcile, missing or duplicate keys) or an MVP accept criterion
fails. A *warning* flags an anomaly in the source data. Checks never fix data;
corrections go through cited ``data/manual/`` overrides.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from . import paths
from .manual import TITLE_ID_RE, Issue, validate_manual_dir

EXAMPLES = 5  # examples quoted per issue
GAPS_LISTED = 50  # missing weekends listed in full up to this many


def check_manual() -> list[Issue]:
    return validate_manual_dir(paths.data_manual())


def _parquet_files() -> list:
    found = []
    for directory in (paths.data_build(), paths.site_data()):
        if directory.is_dir():
            found.extend(sorted(directory.rglob("*.parquet")))
    return found


def _connect():
    import duckdb

    return duckdb.connect()  # private connection; never touch the global default one


def check_built_tables() -> list[Issue]:
    """List built Parquet tables with row counts. Absence is not an error."""
    files = _parquet_files()
    if not files:
        print("Built tables: no built tables yet (data is built in CI)")
        return []
    issues: list[Issue] = []
    con = _connect()
    print("Built tables:")
    root = paths.repo_root()
    for f in files:
        rel = f.relative_to(root).as_posix() if f.is_relative_to(root) else str(f)
        try:
            n = con.execute("SELECT count(*) FROM read_parquet(?)", [str(f)]).fetchall()[0][0]
            print(f"  {rel}: {n} rows")
        except Exception as exc:  # unreadable parquet is a real problem
            issues.append(Issue("error", rel, 0, f"cannot read parquet: {exc}"))
    con.close()
    return issues


def _view(con, name: str, path: Path) -> None:
    """CREATE VIEW over a Parquet file (views can't take prepared parameters)."""
    literal = "'" + str(path).replace("'", "''") + "'"
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet({literal})")


def _site_table(name: str) -> Path | None:
    p = paths.site_data() / f"{name}.parquet"
    return p if p.is_file() else None


def _examples(rows: list[tuple], fmt: Callable[[tuple], str], limit: int = EXAMPLES) -> str:
    shown = "; ".join(fmt(r) for r in rows[:limit])
    return f"e.g. {shown}" + ("; ..." if len(rows) > limit else "")


# --- M1: stat695 ingest -----------------------------------------------------

def check_stat695_report() -> list[Issue]:
    """Reconcile the stat695 row counts and surface the anomalies the ingest counted."""
    path = paths.data_build() / "stat695_report.json"
    if not path.is_file():
        return []
    name = "stat695_report.json"
    r = json.loads(path.read_text(encoding="utf-8"))
    issues: list[Issue] = []
    print(
        f"stat695 ingest: {r['source_rows']} source rows, {r['source_releases']} movie_ids -> "
        f"{r['snapshot_rows']} snapshots, {r['releases']} releases, {r['weekends']} weekends "
        f"({r['weekend_min']} to {r['weekend_max']})"
    )
    print(f"  null values in snapshots: {r['nulls']}")
    print(f"  releases with no release_date: {r['releases_missing_release_date']}")
    print(f"  releases whose title/studio/release_date varies between weeks: {r['releases_with_varying']}")
    print(f"  re-releases detected, by rule: {r['rereleases'] or 'none'}; manual groupings: {r['manual_groups_applied']}")

    accounted = r["snapshot_rows"] + r["exact_duplicates_dropped"] + r["unkeyed_rows"]
    if accounted != r["source_rows"]:
        issues.append(Issue("error", name, 0,
                            f"row counts don't reconcile: {r['snapshot_rows']} snapshots + "
                            f"{r['exact_duplicates_dropped']} duplicates + {r['unkeyed_rows']} unkeyed "
                            f"= {accounted}, but the source has {r['source_rows']} rows"))
    built = paths.data_build() / "stat695_snapshots.parquet"
    if built.is_file():
        con = _connect()
        n = con.execute("SELECT count(*) FROM read_parquet(?)", [str(built)]).fetchone()[0]
        con.close()
        if n != r["snapshot_rows"]:
            issues.append(Issue("error", name, 0,
                                f"stat695_snapshots.parquet has {n} rows, the report says {r['snapshot_rows']}"))
    if r["source_rows"] != r["documented_rows"]:
        issues.append(Issue("warning", name, 0,
                            f"mojo.rda has {r['source_rows']} rows; its docs say {r['documented_rows']}"))
    if r["source_releases"] != r["documented_releases"]:
        issues.append(Issue("warning", name, 0,
                            f"mojo.rda has {r['source_releases']} movie_ids; its docs say {r['documented_releases']}"))
    if r["unkeyed_rows"]:
        ex = "; ".join(f"row {e['_row']} ({e['movie_id']}, {e['weekend_end']})" for e in r["unkeyed_examples"][:EXAMPLES])
        issues.append(Issue("warning", name, 0,
                            f"{r['unkeyed_rows']} source rows have no end_date or movie_id and were left out, e.g. {ex}"))
    if r["exact_duplicates_dropped"]:
        labels = r["duplicate_chart_labels"]
        ex = "; ".join(f"{d['chart']} repeats {d['same_as']} ({d['rows']} rows)" for d in labels[:EXAMPLES])
        issues.append(Issue("warning", name, 0,
                            f"{r['exact_duplicates_dropped']} source rows exactly repeat another row "
                            f"(same weekend, release and figures) and were kept once: {ex}"
                            + ("; ..." if len(labels) > EXAMPLES else "")))
    if r.get("unmarked_string_encoding", "UTF-8") != "UTF-8":
        issues.append(Issue("warning", name, 0,
                            f"strings with no encoding mark weren't valid UTF-8 and were read as "
                            f"{r['unmarked_string_encoding']}; spot-check accented titles"))
    if r["nonintegral_values"]:
        issues.append(Issue("warning", name, 0,
                            f"fractional values rounded to whole numbers: {r['nonintegral_values']}"))
    return issues


# --- snapshots and releases (all sources) -----------------------------------

# --- M2: archived Box Office Mojo weekends --------------------------------------

BOM_REPORT = "bom_weekend_report.json"
BOM_WEEKENDS = "bom_weekend_weekends.csv"
GAP_REASONS = {
    "no_capture": "no capture in either archive (Wayback Machine, Common Crawl)",
    "empty_chart": "archived chart lists no films",
}
UNFINISHED = {
    "error": "archive lookup failed (retried next run)",
    "pending": "not fetched yet: the run's fetch time ran out (continues next run)",
    "unchecked": "not in the Wayback Machine, and the Common Crawl index couldn't be read",
}


def _bom_weekends() -> list[dict] | None:
    path = paths.data_build() / BOM_WEEKENDS
    if not path.is_file():
        return None
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def check_bom_weekend_report() -> list[Issue]:
    path = paths.data_build() / BOM_REPORT
    weekends = _bom_weekends()
    if not path.is_file() or weekends is None:
        return []
    name = BOM_REPORT
    report = json.loads(path.read_text(encoding="utf-8"))
    issues: list[Issue] = []
    main = [w for w in weekends if w["overlap"] != "true"]
    print(f"bom_weekend: {report['weekends']} weekends {report['first_weekend']} to {report['latest_weekend']} "
          f"as of {report['as_of']}: {report['statuses']}; archives {report['archives']}, "
          f"page styles {report['styles']}; {report['snapshot_rows']} snapshots, "
          f"{report['estimate_rows']} still estimates; links {report['links']}; "
          f"release pages {report['release_pages']}")
    for status, why in UNFINISHED.items():
        rows = [w for w in main if w["status"] == status]
        if rows:
            issues.append(Issue("error", name, 0, f"{len(rows)} weekends: {why}, "
                                + _examples([(w["code"], w["notes"]) for w in rows],
                                            lambda r: f"{r[0]} ({r[1][:120]})")))
    overlap_bad = [w for w in weekends if w["overlap"] == "true" and w["status"] != "ok"]
    if overlap_bad:
        issues.append(Issue("warning", name, 0, f"{len(overlap_bad)} stat695 weekends couldn't be re-read for "
                            "stitching, " + _examples([(w["code"], w["status"]) for w in overlap_bad],
                                                      lambda r: f"{r[0]} ({r[1]})")))
    carry = report.get("unlinked_carryovers") or []
    if carry:
        issues.append(Issue("error", name, 0,
                            f"{len(carry)} films charting on {report['first_weekend']} were already in release "
                            "but aren't stitched to a stat695 release, so their total_gross restarts, "
                            + _examples([(c["bom_release_id"], c["title"], c["weeks"]) for c in carry],
                                        lambda r: f"{r[0]} {r[1]!r} (week {r[2]})")))
    if report.get("link_conflicts"):
        issues.append(Issue("warning", name, 0, f"{len(report['link_conflicts'])} stitching conflicts left unlinked, "
                            + _examples([(c,) for c in report["link_conflicts"]], lambda r: r[0])))
    if report.get("unkeyed_rows"):
        issues.append(Issue("warning", name, 0, f"{report['unkeyed_rows']} chart rows had no release link "
                            "and were skipped"))
    return issues


SNAPSHOT_COLUMNS = ("weekend_end", "release_id", "title_id", "rank", "weekend_gross", "theaters",
                    "total_gross", "weeks", "source", "capture_url", "is_estimate")


def check_snapshots() -> list[Issue]:
    path = _site_table("snapshots")
    if path is None:
        return []
    name = "snapshots.parquet"
    issues: list[Issue] = []
    con = _connect()
    _view(con, "s", path)
    cols = [r[0] for r in con.execute("DESCRIBE s").fetchall()]
    missing = [c for c in SNAPSHOT_COLUMNS if c not in cols]
    if missing:
        con.close()
        return [Issue("error", name, 0, f"missing columns {missing}")]

    def rows(sql: str) -> list[tuple]:
        return con.execute(sql).fetchall()

    n_null = rows("SELECT count(*) FROM s WHERE weekend_end IS NULL OR release_id IS NULL")[0][0]
    if n_null:
        issues.append(Issue("error", name, 0, f"{n_null} rows have no weekend_end or release_id"))

    dup_keys = rows("""
        SELECT weekend_end, release_id, count(*) FROM s
        GROUP BY ALL HAVING count(*) > 1 ORDER BY weekend_end, release_id""")
    if dup_keys:
        issues.append(Issue("error", name, 0,
                            f"{len(dup_keys)} (weekend_end, release_id) pairs appear more than once, "
                            + _examples(dup_keys, lambda r: f"{r[1]} on {r[0]} x{r[2]}")))

    dup_ranks = rows("""
        SELECT weekend_end, rank, string_agg(release_id, ', ' ORDER BY release_id) FROM s
        WHERE rank IS NOT NULL GROUP BY weekend_end, rank HAVING count(*) > 1 ORDER BY weekend_end, rank""")
    if dup_ranks:
        weekends = len({r[0] for r in dup_ranks})
        issues.append(Issue("error", name, 0,
                            f"{weekends} weekends have duplicate ranks ({len(dup_ranks)} ranks), "
                            + _examples(dup_ranks, lambda r: f"{r[0]} rank {r[1]}: {r[2]}")))

    decreasing = rows("""
        WITH t AS (
            SELECT release_id, weekend_end, total_gross,
                   lag(total_gross) OVER (PARTITION BY release_id ORDER BY weekend_end) AS prev
            FROM s WHERE total_gross IS NOT NULL)
        SELECT release_id, weekend_end, prev, total_gross FROM t
        WHERE total_gross < prev ORDER BY release_id, weekend_end""")
    if decreasing:
        n_rel = len({r[0] for r in decreasing})
        issues.append(Issue("warning", name, 0,
                            f"total_gross goes down {len(decreasing)} times in {n_rel} releases (flagged, not fixed), "
                            + _examples(decreasing, lambda r: f"{r[0]} {r[1]}: {r[2]:,} -> {r[3]:,}")))

    below = rows("""
        SELECT release_id, weekend_end, weekend_gross, total_gross FROM s
        WHERE total_gross < weekend_gross ORDER BY weekend_end, release_id""")
    if below:
        issues.append(Issue("warning", name, 0,
                            f"{len(below)} rows have total_gross below weekend_gross, "
                            + _examples(below, lambda r: f"{r[0]} {r[1]}: weekend {r[2]:,}, total {r[3]:,}")))

    not_sunday = rows("""
        SELECT weekend_end, dayname(weekend_end) FROM (SELECT DISTINCT weekend_end FROM s)
        WHERE dayofweek(weekend_end) <> 0 ORDER BY weekend_end""")
    if not_sunday:
        issues.append(Issue("warning", name, 0,
                            f"{len(not_sunday)} weekends don't end on a Sunday, "
                            + _examples(not_sunday, lambda r: f"{r[0]} ({r[1]})")))

    # Weekly coverage: every Sunday from the first chart through the latest completed weekend
    # (as of the M2 run) should have one, or be in the gap report with a reason.
    # A chart that ends on a holiday Monday counts for the Sunday before it.
    report_path = paths.data_build() / BOM_REPORT
    latest = None
    if report_path.is_file():
        latest = json.loads(report_path.read_text(encoding="utf-8")).get("latest_weekend_end")
    gaps = rows(f"""
        WITH w AS (SELECT DISTINCT CAST(weekend_end - CAST(dayofweek(weekend_end) AS INTEGER) AS DATE) AS sun FROM s),
        all_sundays AS (
            SELECT CAST(unnest(generate_series(min(sun), greatest(max(sun), {"DATE '" + latest + "'" if latest else "max(sun)"}),
                                               INTERVAL 7 DAY)) AS DATE) AS sun FROM w)
        SELECT sun FROM all_sundays WHERE sun NOT IN (SELECT sun FROM w) ORDER BY sun""")
    span = rows("SELECT min(weekend_end), max(weekend_end), count(DISTINCT weekend_end) FROM s")[0]
    print(f"snapshots: {span[2]} weekends from {span[0]} to {span[1]}"
          + (f" (latest completed weekend {latest})" if latest else "") + f", {len(gaps)} missing")
    status = {w["weekend_end"]: w for w in (_bom_weekends() or []) if w["overlap"] != "true"}
    explained: dict[str, list[tuple]] = {}
    unexplained = []
    for (sun,) in gaps:
        w = status.get(sun.isoformat())
        if w and w["status"] in GAP_REASONS:
            explained.setdefault(w["status"], []).append((sun, w["code"]))
        else:
            unexplained.append((sun, w["status"] if w else "no entry"))
    for st, items in explained.items():
        issues.append(Issue("warning", name, 0,
                            f"gap report: {len(items)} weekends have no chart, {GAP_REASONS[st]}: "
                            + _examples(items, lambda r: f"{r[1]} (ending {r[0]})", limit=GAPS_LISTED)))
    if unexplained:
        issues.append(Issue("error", name, 0,
                            f"{len(unexplained)} weekends are missing without a gap-report reason, "
                            + _examples(unexplained, lambda r: f"weekend ending {r[0]} ({r[1]})", limit=GAPS_LISTED)))
    con.close()
    return issues


def check_releases() -> list[Issue]:
    path = _site_table("releases")
    if path is None:
        return []
    name = "releases.parquet"
    issues: list[Issue] = []
    con = _connect()
    _view(con, "r", path)
    dup = con.execute("SELECT release_id FROM r GROUP BY ALL HAVING count(*) > 1").fetchall()
    if dup:
        issues.append(Issue("error", name, 0, f"{len(dup)} release_ids appear more than once, "
                            + _examples(dup, lambda x: x[0])))
    bad = con.execute("SELECT release_id, title_id FROM r WHERE NOT regexp_full_match(coalesce(title_id, ''), ?)",
                      [TITLE_ID_RE.pattern.strip("^$")]).fetchall()
    if bad:
        issues.append(Issue("error", name, 0, f"{len(bad)} releases have an invalid title_id, "
                            + _examples(bad, lambda x: f"{x[0]}: {x[1]!r}")))
    cols = [r[0] for r in con.execute("DESCRIBE r").fetchall()]
    if {"is_rerelease", "first_weekend"} <= set(cols):
        # A title has one first release; the rest are re-releases. Two first releases usually
        # mean a grouping or an M3 match joined two films, or one run was charted under two ids
        # (which would count it twice). Biggest titles first.
        snaps_path = _site_table("snapshots")
        if snaps_path is not None:
            _view(con, "g_s", snaps_path)
            gross = "(SELECT release_id, max(total_gross) AS g FROM g_s GROUP BY 1)"
        else:
            gross = "(SELECT NULL::VARCHAR AS release_id, 0 AS g)"
        two_firsts = con.execute(f"""
            SELECT title_id, string_agg(title || ' (' || release_id || ')', '; ' ORDER BY first_weekend, release_id),
                   sum(coalesce(g, 0)) AS total
            FROM r LEFT JOIN {gross} USING (release_id) GROUP BY 1
            HAVING count(*) FILTER (WHERE NOT coalesce(is_rerelease, false)) > 1
            ORDER BY total DESC, 1""").fetchall()
        if two_firsts:
            issues.append(Issue("warning", name, 0,
                                f"{len(two_firsts)} title_ids group more than one first release (check the grouping "
                                "or the match), biggest first, "
                                + _examples(two_firsts, lambda x: f"{x[0]}: {x[1]}", limit=10)))
    snaps = _site_table("snapshots")
    if snaps is not None:
        _view(con, "s", snaps)
        orphans = con.execute("""
            SELECT DISTINCT s.release_id FROM s ANTI JOIN r USING (release_id) ORDER BY 1""").fetchall()
        if orphans:
            issues.append(Issue("error", name, 0, f"{len(orphans)} snapshot release_ids are missing from releases, "
                                + _examples(orphans, lambda x: x[0])))
        if "bom_release_id" in cols:
            dup_rl = con.execute("""
                SELECT bom_release_id, string_agg(release_id, ', ') FROM r WHERE bom_release_id IS NOT NULL
                GROUP BY 1 HAVING count(*) > 1 ORDER BY 1""").fetchall()
            if dup_rl:
                issues.append(Issue("error", name, 0, f"{len(dup_rl)} rl release ids belong to several releases, "
                                    + _examples(dup_rl, lambda x: f"{x[0]}: {x[1]}")))
        mismatched = con.execute("""
            SELECT DISTINCT s.release_id, s.title_id, r.title_id FROM s JOIN r USING (release_id)
            WHERE s.title_id IS DISTINCT FROM r.title_id ORDER BY 1""").fetchall()
        if mismatched:
            issues.append(Issue("error", name, 0, f"{len(mismatched)} releases have a different title_id in snapshots, "
                                + _examples(mismatched, lambda x: f"{x[0]}: {x[1]} vs {x[2]}")))
    con.close()
    return issues


# --- M3: identity matching -------------------------------------------------------

MATCH_REPORT = "match_report.json"
WIKIDATA_REPORT = "wikidata_report.json"
MATCH_NOTES = {
    "group_conflicts": "groups whose releases matched different titles (unmatched members follow the original)",
    "release_page_vs_p1237": "releases whose archived release page and Wikidata P1237 disagree (the page wins)",
    "release_page_tt_not_on_wikidata": "release-page IMDb ids with no Wikidata item (P345)",
    "p1237_on_several_items": "releases whose legacy id is on several Wikidata items (the best-known is used)",
}


def check_wikidata_report() -> list[Issue]:
    path = paths.data_build() / WIKIDATA_REPORT
    if not path.is_file():
        return []
    name = WIKIDATA_REPORT
    wd = json.loads(path.read_text(encoding="utf-8"))
    issues: list[Issue] = []
    print(f"wikidata: snapshot {wd['snapshot']} from {wd['endpoint']}: {wd['items']} items, "
          f"{wd['items_with_tt']} with an IMDb id, {wd['bom_ids']} legacy Box Office Mojo ids on "
          f"{wd['items_with_bom_id']} items; release-page tt lookup {wd['release_page_tt_lookup']}")
    if wd.get("stale_reason"):
        issues.append(Issue("warning", name, 0, f"this month's snapshot couldn't be fetched, so {wd['snapshot']}'s "
                            f"was used ({wd['stale_reason'][:200]})"))
    multi = wd.get("bom_ids_on_several_items") or []
    if multi:
        issues.append(Issue("warning", name, 0, f"{len(multi)} legacy Box Office Mojo ids (P1237) are on several "
                            "Wikidata items (worth fixing upstream), " + _examples([(e,) for e in multi], lambda x: x[0])))
    if (wd.get("release_page_tt_lookup") or {}).get("error"):
        issues.append(Issue("warning", name, 0,
                            f"the P345 lookup of release-page tt ids failed: {wd['release_page_tt_lookup']['error']}"))
    return issues


def check_match_report() -> list[Issue]:
    """Accept: >= 97% of nominal gross matched to an IMDb id, and every one of the top 1,000 releases."""
    path = paths.data_build() / MATCH_REPORT
    if not path.is_file():
        return []
    name = MATCH_REPORT
    r = json.loads(path.read_text(encoding="utf-8"))
    issues: list[Issue] = []
    methods = "; ".join(f"{k} {v['releases']} ({v['share']:.1%} of gross)" for k, v in r["by_method"].items())
    print(f"match: {r['releases']} releases -> {r['titles']} titles, {r['matched_share']:.2%} of gross matched "
          f"to an IMDb id; {methods}; {r['ambiguous_count']} ambiguous title matches left unmatched")
    if not r["films_loaded"]:
        return [Issue("error", name, 0, "no Wikidata snapshot was loaded, so nothing was matched")]
    if r["matched_share"] < r["matched_target"]:
        issues.append(Issue("error", name, 0, f"only {r['matched_share']:.2%} of nominal gross is matched to an "
                            f"IMDb id (accept: at least {r['matched_target']:.0%})"))
    if r["top_unmatched"]:
        issues.append(Issue("error", name, 0,
                            f"{len(r['top_unmatched'])} of the top {r['top_releases']} releases by gross have no "
                            "IMDb id (accept: all of them; add a cited row to data/manual/id_overrides.csv), "
                            + _examples(r["top_unmatched"], lambda x: f"{x['release_id']} {x['title']!r} "
                                        f"(${x['gross'] or 0:,}, {x['method']})", limit=GAPS_LISTED)))
    for key, why in MATCH_NOTES.items():
        note = r["notes"].get(key)
        if note and note["count"]:
            issues.append(Issue("warning", name, 0, f"{note['count']} {why}, "
                                + _examples([(e,) for e in note["examples"]], lambda x: x[0])))
    return issues


def check_titles() -> list[Issue]:
    path = _site_table("titles")
    if path is None:
        return []
    name = "titles.parquet"
    issues: list[Issue] = []
    con = _connect()
    _view(con, "t", path)
    dup = con.execute("SELECT title_id FROM t GROUP BY 1 HAVING count(*) > 1 ORDER BY 1").fetchall()
    if dup:
        issues.append(Issue("error", name, 0, f"{len(dup)} title_ids appear more than once, "
                            + _examples(dup, lambda x: x[0])))
    bad = con.execute("SELECT title_id FROM t WHERE NOT regexp_full_match(coalesce(title_id, ''), ?) ORDER BY 1",
                      [TITLE_ID_RE.pattern.strip("^$")]).fetchall()
    if bad:
        issues.append(Issue("error", name, 0, f"{len(bad)} invalid title_ids, " + _examples(bad, lambda x: repr(x[0]))))
    no_qid = con.execute("SELECT title_id FROM t WHERE title_id LIKE 'tt%' AND wikidata_qid IS NULL ORDER BY 1").fetchall()
    if no_qid:
        issues.append(Issue("warning", name, 0, f"{len(no_qid)} titles with an IMDb id have no Wikidata item, "
                            + _examples(no_qid, lambda x: x[0])))
    rels = _site_table("releases")
    if rels is not None:
        _view(con, "r", rels)
        missing = con.execute("SELECT DISTINCT title_id FROM r ANTI JOIN t USING (title_id) ORDER BY 1").fetchall()
        if missing:
            issues.append(Issue("error", name, 0, f"{len(missing)} release title_ids are missing from titles, "
                                + _examples(missing, lambda x: x[0])))
        orphan = con.execute("""SELECT DISTINCT title_id FROM t ANTI JOIN r USING (title_id)
                                WHERE pre1982_baseline_gross IS NULL ORDER BY 1""").fetchall()
        if orphan:
            issues.append(Issue("error", name, 0, f"{len(orphan)} titles have neither a release nor a baseline, "
                                + _examples(orphan, lambda x: x[0])))
    con.close()
    return issues


# ---------------------------------------------------------------------------
# Each check is a zero-argument callable returning a list of Issue. Checks must
# flag anomalies, never silently fix them.
# ---------------------------------------------------------------------------
CHECKS: list[Callable[[], list[Issue]]] = [
    check_manual,
    check_built_tables,
    check_stat695_report,
    check_bom_weekend_report,
    check_snapshots,
    check_releases,
    check_wikidata_report,
    check_match_report,
    check_titles,
]


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):  # film titles on a Windows console
        sys.stdout.reconfigure(errors="backslashreplace")
    issues: list[Issue] = []
    for check in CHECKS:
        issues.extend(check())
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    print()
    for issue in issues:
        print(issue)
    print(f"\nchecks: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
