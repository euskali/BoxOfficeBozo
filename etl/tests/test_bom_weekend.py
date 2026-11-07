from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from bom_html import new_weekend_page, old_weekend_page, release_page
from boffo_etl import archives
from boffo_etl.fetch import FetchDisabledError, Fetcher
from boffo_etl.sources import bom_weekend as bw
from boffo_etl.sources.stat695 import RELEASE_SCHEMA, SNAPSHOT_SCHEMA
from fake_archive import FakeArchive

TODAY = date(2017, 2, 21)  # a Tuesday: the latest completed weekend is 2017W07 (Feb 17-19)
NEW = "https://www.boxofficemojo.com/weekend/{}/"
OLD = "http://www.boxofficemojo.com/weekend/chart/?yr=2017&wknd={:02d}&p=.htm"


# --- weekend codes and windows ----------------------------------------------------

@pytest.mark.parametrize("sunday, code", [
    (date(2017, 1, 1), "2016W53"), (date(2017, 1, 8), "2017W01"), (date(2020, 1, 5), "2020W01"),
    (date(2021, 1, 3), "2021W01"), (date(2019, 5, 26), "2019W21"), (date(2026, 11, 1), "2026W44"),
])
def test_weekend_codes_count_fridays(sunday, code):
    assert bw.weekend_code(sunday) == code
    assert bw.code_sunday(code) == sunday


def test_latest_completed_sunday():
    assert bw.latest_completed_sunday(date(2026, 11, 6)) == date(2026, 11, 1)  # Friday
    assert bw.latest_completed_sunday(date(2026, 11, 2)) == date(2026, 11, 1)  # Monday
    assert bw.latest_completed_sunday(date(2026, 11, 1)) == date(2026, 10, 25)  # Sunday: not done yet


def test_cdx_windows():
    today = date(2026, 11, 6)
    assert bw.cdx_windows(date(2017, 1, 8), today) == [
        ("20170109", "20170310"), ("20170109", "20230110"), ("20170109", "202611")]
    assert bw.cdx_windows(date(2024, 5, 5), today) == [("20240506", "20240705"), ("20240506", "202611")]
    assert bw.cdx_windows(date(2026, 10, 25), today) == [("20261026", "20261106")]
    assert bw.cdx_windows(date(2017, 1, 8), today, not_before=date(2019, 10, 1)) == [
        ("20170109", "20230110"), ("20170109", "202611")]


def test_order_candidates_prefers_closest_after_the_next_monday():
    def cap(ts, mime="text/html"):
        return archives.Capture("wayback", archives.parse_ts(ts), "u", 200, mime)

    caps = [cap("20200105230000"), cap("20200107000000"), cap("20200109000000"), cap("20200114000000"),
            cap("20200120000000"), cap("20200113000000", mime="application/json")]
    ordered = archives.order_candidates(caps, earliest=archives.parse_ts("20200106"),
                                        preferred_after=archives.parse_ts("20200113"))
    assert [c.ts14 for c in ordered] == ["20200114000000", "20200120000000", "20200109000000", "20200107000000"]


# --- a small world ----------------------------------------------------------------------

def legacy_tables():
    rels = [
        ("legacy:rogue", "bb_rogue", "Rogue Mission"), ("legacy:singalong", "bb_singalong", "Sing Along"),
        ("legacy:lalalane", "bb_lalalane", "La La Lane"), ("legacy:oldie", "bb_oldie", "Oldie"),
        ("legacy:gone", "bb_gone", "Gone Girlish"),
    ]
    releases = pl.DataFrame([{
        "release_id": r, "title_id": t, "label": None, "release_date": None, "source_key": r[7:],
        "source": "stat695", "title": title, "distributor": "BV", "genres": None, "mpaa": None,
        "first_weekend": date(2016, 11, 20), "last_weekend": date(2017, 1, 1), "weekends": 4,
        "is_rerelease": False, "rerelease_reason": None, "parent_release_id": None, "group_source": "auto",
    } for r, t, title in rels], schema=RELEASE_SCHEMA)
    snaps = []
    weekends = [date(2016, 12, 11), date(2016, 12, 18), date(2016, 12, 25), date(2017, 1, 1)]
    for i, wk in enumerate(weekends):
        snaps += [
            (wk, "legacy:rogue", "bb_rogue", 1, 50_000_000 - i, 300_000_000 + i * 50_000_000, i + 1),
            (wk, "legacy:singalong", "bb_singalong", 2, 30_000_000 - i, 100_000_000 + i * 30_000_000, i + 1),
            (wk, "legacy:lalalane", "bb_lalalane", 3, 5_000_000 - i, 20_000_000 + i * 5_000_000, i + 3),
        ]
        if wk <= date(2016, 12, 18):
            snaps.append((wk, "legacy:gone", "bb_gone", 4, 10_000 - i, 900_000 + i, 9 + i))
    snaps.append((date(2016, 11, 20), "legacy:oldie", "bb_oldie", 9, 100_000, 1_000_000, 5))
    snaps = pl.DataFrame([{
        "weekend_end": w, "release_id": r, "title_id": t, "rank": k, "weekend_gross": g, "theaters": None,
        "total_gross": tg, "weeks": n, "source": "stat695", "capture_url": None, "is_estimate": False,
    } for w, r, t, k, g, tg, n in snaps], schema=SNAPSHOT_SCHEMA)
    return snaps, releases


def overlap_rows(i):
    return [
        {"rank": 1, "rl": "rl100", "title": "Rogue Mission", "gross": 50_000_000 - i,
         "total": 300_000_000 + i * 50_000_000, "weeks": i + 1},
        {"rank": 2, "rl": "rl200", "title": "Sing Along", "gross": 30_000_000 - i,
         "total": 100_000_000 + i * 30_000_000, "weeks": i + 1},
        # Revised by a few dollars since stat695's scrape, but the same total gross.
        {"rank": 3, "rl": "rl300", "title": "La La Lane", "gross": 5_000_000 - i + 7,
         "total": 20_000_000 + i * 5_000_000, "weeks": i + 3},
    ]


def main_rows(n, *, est=False):
    """Rows for 2017W0n."""
    return [
        {"rank": 1, "rl": "rl100", "title": "Rogue Mission", "gross": 20_000_000 // n, "theaters": 4000,
         "total": 460_000_000 + n * 10_000_000, "weeks": 4 + n, "dist": "Walt Disney Studios", "est": est},
        {"rank": 2, "rl": "rl500", "title": "Brand New", "gross": 15_000_000 // n, "total": n * 15_000_000,
         "weeks": n, "new": n == 1, "est": est},
        {"rank": 3, "rl": "rl200", "title": "Sing Along", "gross": 9_000_000 // n,
         "total": 200_000_000 + n * 1_000_000, "weeks": 4 + n, "est": est},
        {"rank": 4, "rl": "rl300", "title": "La La Lane", "gross": 4_000_000 // n,
         "total": 40_000_000 + n * 1_000_000, "weeks": 6 + n, "est": est},
        {"rank": 5, "rl": "rl400", "title": "Oldie", "gross": 50_000 // n, "total": 1_100_000 + n * 50_000,
         "weeks": 12 + n, "est": est},
        {"rank": 6, "rl": "rl600", "title": "The Classic", "label": "2017 re-release", "gross": 1_000,
         "total": 1_000 * n, "weeks": n, "est": est},
    ]


def dates(sunday):
    f = sunday - timedelta(days=2)
    return f"{f.strftime('%B')} {f.day}-{sunday.day}, {sunday.year}" if f.month == sunday.month else \
        f"{f.strftime('%B')} {f.day}-{sunday.strftime('%B')} {sunday.day}, {sunday.year}"


def world() -> FakeArchive:
    fa = FakeArchive()
    for i, code in enumerate(["2016W50", "2016W51", "2016W52", "2016W53"]):
        s = bw.code_sunday(code)
        fa.add_wayback(NEW.format(code), "20170110000000", new_weekend_page(
            int(code[:4]), int(code[5:]), dates(s), overlap_rows(i)))

    def new(n, ts, *, rows=None, dates_text=None):
        code = f"2017W{n:02d}"
        s = bw.code_sunday(code)
        fa.add_wayback(NEW.format(code), ts, new_weekend_page(2017, n, dates_text or dates(s),
                                                              main_rows(n) if rows is None else rows))

    new(1, "20170109100000", rows=main_rows(1, est=True))  # Monday morning: estimates
    new(1, "20170117120000")  # after the next Monday: this one wins
    fa.add_wayback(NEW.format("2017W02"), "20170124000000", "<html><title>Robot check</title></html>")
    new(2, "20170125000000")
    new(3, "20170130000000", dates_text="January 13-15, 2017")  # the wrong weekend's page
    new(3, "20170131000000")
    fa.add_wayback(OLD.format(4), "20170207000000", old_weekend_page("January 27-29, 2017", [
        {"rank": 1, "lw": "1", "legacy": "rogue", "title": "Rogue Mission", "gross": 5_000_000,
         "total": 500_000_000, "weeks": 8},
        {"rank": 2, "lw": "2", "legacy": "brandnew2017", "title": "Brand New", "gross": 3_000_000,
         "total": 60_000_000, "weeks": 4},
        {"rank": 3, "legacy": "fresh2017", "title": "Fresh Thing", "gross": 1_000_000, "total": 1_000_000,
         "weeks": 1},
    ]))
    fa.add_crawl("CC-MAIN-2016-50", "2016-12-01T00:00:00", "2016-12-12T00:00:00")
    fa.add_crawl("CC-MAIN-2017-09", "2017-02-18T00:00:00", "2017-03-01T00:00:00")
    fa.add_cc("CC-MAIN-2017-09", NEW.format("2017W05"), "20170219000000",
              new_weekend_page(2017, 5, dates(bw.code_sunday("2017W05")), main_rows(5)))
    new(7, "20170220000000", rows=main_rows(7, est=True))  # only a Monday capture so far
    return fa


@pytest.fixture
def fetch_on(repo, monkeypatch):
    monkeypatch.setenv("BOFFO_FETCH", "1")


def fetcher_for(fa: FakeArchive) -> Fetcher:
    return Fetcher(fa.client(), min_interval=0, sleep=lambda s: None)


def run_world(fa, **kw):
    snaps, rels = legacy_tables()
    return bw.ingest(fetcher_for(fa), TODAY, snaps, rels, log=lambda *a: None, retry_pause=0, **kw)


def by_code(ing):
    return {r.code: r for r in ing.weekends}


def test_ingest_end_to_end(fetch_on):
    fa = world()
    ing = run_world(fa)
    res = by_code(ing)
    assert {c: res[c].status for c in res} == {
        "2016W50": "ok", "2016W51": "ok", "2016W52": "ok", "2016W53": "ok",
        "2017W01": "ok", "2017W02": "ok", "2017W03": "ok", "2017W04": "ok", "2017W05": "ok",
        "2017W06": "no_capture", "2017W07": "ok"}
    assert res["2017W01"].capture.ts14 == "20170117120000"
    assert res["2017W02"].capture.ts14 == "20170125000000" and "not a chart" in " ".join(res["2017W02"].notes)
    assert res["2017W03"].capture.ts14 == "20170131000000" and "not the weekend" in " ".join(res["2017W03"].notes)
    assert (res["2017W04"].style, res["2017W04"].archive) == ("old", "wayback")
    assert (res["2017W05"].archive, res["2017W05"].style) == ("commoncrawl", "new")
    assert res["2017W05"].capture_url.startswith("https://data.commoncrawl.org/crawl-data/CC-MAIN-2017-09/")
    assert res["2017W07"].capture.ts14 == "20170220000000"
    assert ing.report["first_weekend"] == "2017W01" and ing.report["latest_weekend"] == "2017W07"

    links = {r["bom_release_id"]: (r["release_id"], r["method"]) for r in ing.links.to_dicts()}
    assert links == {"rl100": ("legacy:rogue", "overlap"), "rl200": ("legacy:singalong", "overlap"),
                     "rl300": ("legacy:lalalane", "overlap"), "rl400": ("legacy:oldie", "continuity")}
    assert ing.report["unlinked_carryovers"] == []

    s = ing.snapshots
    assert s.schema == pl.Schema(SNAPSHOT_SCHEMA)
    assert s["weekend_end"].min() == date(2017, 1, 8) and s.filter(pl.col("weekend_end") == date(2017, 2, 12)).height == 0
    rogue = s.filter(pl.col("release_id") == "legacy:rogue").sort("weekend_end")
    assert rogue["title_id"].unique().to_list() == ["bb_rogue"]
    assert rogue["total_gross"].to_list() == sorted(rogue["total_gross"].to_list())  # continuous
    assert rogue.height == 6  # W01-W05 and W07
    brand = s.filter(pl.col("release_id") == "bom:rl500")
    assert brand.height == 6  # the old-style W04 row joined rl500 by title
    assert s.filter(pl.col("release_id") == "legacy:fresh2017").height == 1
    w01 = s.filter(pl.col("weekend_end") == date(2017, 1, 8))
    assert not w01["is_estimate"].any()
    assert s.filter(pl.col("weekend_end") == date(2017, 2, 19))["is_estimate"].all()
    assert set(s["source"].unique().to_list()) == {"wayback", "commoncrawl"}
    assert s.filter(pl.col("weekend_end") == date(2017, 1, 8))["capture_url"].unique().to_list() == [
        "https://web.archive.org/web/20170117120000/https://www.boxofficemojo.com/weekend/2017W01/"]

    r = {x["release_id"]: x for x in ing.releases.to_dicts()}
    assert set(r) == {"bom:rl500", "bom:rl600", "legacy:fresh2017"}
    assert r["bom:rl600"]["is_rerelease"] and r["bom:rl600"]["rerelease_reason"] == "bom_label"
    assert r["bom:rl600"]["label"] == "2017 re-release"
    assert r["bom:rl500"]["title_id"] == "bb_rl500" and not r["bom:rl500"]["is_rerelease"]
    assert r["bom:rl500"]["weekends"] == 6 and r["bom:rl500"]["source"] == "bom_weekend"
    assert r["legacy:fresh2017"]["title_id"] == "bb_fresh2017"
    assert ing.releases.schema == pl.Schema(RELEASE_SCHEMA)


def test_ingest_rerun_offline_uses_only_the_cache(repo, monkeypatch):
    monkeypatch.setenv("BOFFO_FETCH", "1")
    first = run_world(world())
    monkeypatch.delenv("BOFFO_FETCH")
    fa = FakeArchive()  # an empty archive: any request would find nothing
    again = run_world(fa)
    assert fa.requests == []
    assert again.snapshots.equals(first.snapshots)
    assert again.releases.equals(first.releases)


def test_ingest_offline_with_empty_cache_raises(repo):
    with pytest.raises(FetchDisabledError):
        run_world(world())


def test_out_of_time_marks_weekends_pending(fetch_on):
    ing = run_world(world(), minutes=0)
    assert set(r.status for r in ing.weekends) == {"pending"}


def test_failed_lookup_is_an_error_not_a_gap(fetch_on):
    fa = world()
    fa.fail.append("2017W02")
    res = by_code(run_world(fa))
    assert res["2017W02"].status == "error"
    assert res["2017W01"].status == "ok"


def test_failed_lookup_gets_a_second_try(fetch_on):
    fa = world()
    fa.fail_times["weekend%2F2017W02"] = 4  # every attempt of the first lookup
    res = by_code(run_world(fa))
    assert res["2017W02"].status == "ok"
    assert any(n.startswith("wayback lookup failed") for n in res["2017W02"].notes)
    assert res["2017W02"].notes[-1].startswith("second try: ")


def test_unreadable_common_crawl_index_leaves_the_weekend_unchecked(fetch_on):
    fa = world()
    fa.fail.append("index.commoncrawl.org")
    res = by_code(run_world(fa))
    assert res["2017W05"].status == "unchecked"
    assert res["2017W06"].status == "unchecked"


def test_write_outputs(repo, fetch_on):
    ing = run_world(world())
    out = repo / "data" / "build"
    bw.write_outputs(ing, out)
    weekends = pl.read_csv(out / "bom_weekend_weekends.csv")
    assert weekends.height == 11
    assert weekends.filter(pl.col("overlap"))["code"].to_list() == ["2016W50", "2016W51", "2016W52", "2016W53"]
    gap = weekends.filter(pl.col("code") == "2017W06").to_dicts()[0]
    assert gap["status"] == "no_capture" and gap["weekend_end"] == "2017-02-12"
    for name in ("bom_weekend_snapshots", "bom_weekend_releases", "bom_weekend_links", "bom_release_pages"):
        assert (out / f"{name}.parquet").is_file()
    assert (out / "bom_weekend_report.json").is_file()


# --- stitching ---------------------------------------------------------------------------

def test_match_weekend_is_one_to_one_and_needs_evidence():
    legacy = [{"release_id": "legacy:a", "title": "Alpha", "weekend_gross": 100, "total_gross": 1000},
              {"release_id": "legacy:b", "title": "Beta", "weekend_gross": 100, "total_gross": 2000},
              {"release_id": "legacy:c", "title": "Gamma", "weekend_gross": 5, "total_gross": 50}]
    new = [{"key": "rl1", "title": "Alpha", "weekend_gross": 100, "total_gross": 1000},
           {"key": "rl2", "title": "Beta", "weekend_gross": 100, "total_gross": 2001},
           {"key": "rl3", "title": "Delta", "weekend_gross": 5, "total_gross": 51}]
    assert sorted(bw.match_weekend(legacy, new)) == [("legacy:a", "rl1", 0), ("legacy:b", "rl2", 0)]


def test_match_weekend_handles_renamed_and_year_tagged_titles():
    legacy = [{"release_id": "legacy:passengers2016", "title": "Passengers (2016)", "rank": 3,
               "weekend_gross": 8_000_000, "total_gross": 61_000_000},
              {"release_id": "legacy:sw7", "title": "The Force Unleashed", "rank": 9,
               "weekend_gross": 2_500_000, "total_gross": 900_000_000},
              {"release_id": "legacy:tiny", "title": "Tiny Film", "rank": 40, "weekend_gross": 5_000,
               "total_gross": 70_000}]
    new = [{"key": "rl1", "title": "Passengers", "rank": 3, "weekend_gross": 8_000_100, "total_gross": 61_000_000},
           {"key": "rl2", "title": "Star Wars: Episode VII - The Force Unleashed", "rank": 9,
            "weekend_gross": 2_500_000, "total_gross": 900_050_000},
           {"key": "rl3", "title": "Another Tiny Film", "rank": 41, "weekend_gross": 5_000, "total_gross": 9_000}]
    assert sorted(bw.match_weekend(legacy, new)) == [("legacy:passengers2016", "rl1", 1), ("legacy:sw7", "rl2", 2)]
    assert bw.title_similarity("Passengers (2016)", "Passengers") == 100


def test_link_continuity_needs_a_unique_title_and_growing_totals():
    main = pl.DataFrame([
        {"key": "rl1", "style": "new", "title": "Comeback", "weekend_end": date(2017, 3, 5), "weeks": 20,
         "total_gross": 5_000},
        {"key": "rl2", "style": "new", "title": "Shrinker", "weekend_end": date(2017, 3, 5), "weeks": 20,
         "total_gross": 10},
        {"key": "rl3", "style": "new", "title": "Debut", "weekend_end": date(2017, 3, 5), "weeks": 1,
         "total_gross": 10},
    ])
    last = pl.DataFrame([
        {"release_id": "legacy:comeback", "title": "Comeback", "last_weekend": date(2016, 11, 6),
         "total_gross": 4_000, "weeks": 10},
        {"release_id": "legacy:shrinker", "title": "Shrinker", "last_weekend": date(2016, 11, 6),
         "total_gross": 4_000, "weeks": 10},
        {"release_id": "legacy:debut", "title": "Debut", "last_weekend": date(2016, 11, 6),
         "total_gross": 1, "weeks": 1},
    ])
    links = bw.link_continuity(main, last, {}, date(2017, 1, 1))
    assert {k: v.release_id for k, v in links.items()} == {"rl1": "legacy:comeback"}
    # 17 weeks passed since Nov 6, so week 10 can't become week 40.
    jumped = main.with_columns(pl.when(pl.col("key") == "rl1").then(40).otherwise(pl.col("weeks")).alias("weeks"))
    assert bw.link_continuity(jumped, last, {}, date(2017, 1, 1)) == {}


def test_carryover_report_separates_missed_links_from_late_tracking(fetch_on):
    fa = world()
    rows = main_rows(1) + [
        {"rank": 7, "rl": "rl900", "title": "Sing Along", "gross": 10, "total": 10, "weeks": 3},
        {"rank": 8, "rl": "rl901", "title": "Never Seen Before", "gross": 10, "total": 10, "weeks": 3},
    ]
    s = bw.code_sunday("2017W01")
    fa.add_wayback(NEW.format("2017W01"), "20170116000000", new_weekend_page(2017, 1, dates(s), rows))
    rep = run_world(fa).report
    # rl900 is a second "Sing Along" whose total can't continue legacy:singalong's: flagged for a look.
    assert [c["bom_release_id"] for c in rep["unlinked_carryovers"]] == ["rl900"]
    assert [c["bom_release_id"] for c in rep["carryovers_tracked_late"]] == ["rl901"]


# --- release pages ------------------------------------------------------------------------

def test_release_pages_budget_and_tt_grouping(fetch_on):
    fa = FakeArchive()
    rel = "https://www.boxofficemojo.com/release/{}/"
    fa.add_wayback(rel.format("rl100"), "20220101000000", release_page("Rogue Mission", tt="tt0000100",
                                                                       release_date=date(2016, 12, 16)))
    fa.add_wayback(rel.format("rl700"), "20230101000000", release_page("Rogue Mission", tt="tt0000100",
                                                                       release_date=date(2023, 5, 4)))
    fetcher = fetcher_for(fa)
    import time

    pages, stats = bw.release_pages(fetcher, ["rl100", "rl700", "rl800"], lookups=2,
                                    deadline=time.monotonic() + 60)
    assert [p["rl_id"] for p in pages] == ["rl100", "rl700"] and stats["not_reached"] == 1
    assert pages[0]["tt_id"] == "tt0000100" and pages[0]["release_date"] == date(2016, 12, 16)

    rows = pl.DataFrame([
        {"code": "2023W18", "weekend_end": date(2023, 5, 7), "style": "new", "key": "rl700", "rank": 9,
         "title": "Rogue Mission", "label": "2023 re-release", "weekend_gross": 1, "theaters": None,
         "total_gross": 1, "weeks": 1, "distributor": None, "is_new": True, "is_estimate": False,
         "source": "wayback", "capture_url": "u"},
    ], schema=bw.ROW_SCHEMA)
    info = {p["rl_id"]: bw.bom_pages.ReleaseInfo(**{k: p[k] for k in (
        "tt_id", "title", "release_date", "mpaa", "genres", "running_time", "distributor")}) for p in pages}
    links = {"rl100": bw.Link("rl100", "legacy:rogue", "overlap", 4, "")}
    _, rels_new = legacy_tables()
    snaps, releases, _ = bw.assign_releases(rows, links, rels_new, info)
    r = releases.to_dicts()[0]
    assert (r["release_id"], r["title_id"], r["parent_release_id"], r["release_date"]) == (
        "bom:rl700", "bb_rogue", "legacy:rogue", date(2023, 5, 4))
    assert snaps["title_id"].to_list() == ["bb_rogue"]
