from __future__ import annotations

import csv
import json
from datetime import date, timedelta

import polars as pl
import pytest

from boffo_etl import build, match
from boffo_etl.sources import wikidata as wd
from boffo_etl.sources.stat695 import SNAPSHOT_SCHEMA


def film(qid, label, year, *, tt=None, aliases=(), boms=(), sitelinks=10, us=None, other=None):
    dates = [{"date": None, "year": year, "precision": 9, "place": None}]
    if us:
        dates.append({"date": us, "year": us.year, "precision": 11, "place": "Q30"})
    if other:
        dates.append({"date": other, "year": other.year, "precision": 11, "place": "Q142"})
    return {"qid": qid, "tt": tt, "tts": [tt] if tt else [], "label": label, "aliases": list(aliases),
            "sitelinks": sitelinks, "dates": dates, "bom_ids": list(boms), "origin": "test"}


FILMS = [
    film("Q44578", "Titanic", 1997, tt="tt0120338", boms=["titanic"], sitelinks=90, us=date(1997, 12, 19)),
    film("Q9001", "Rogue Mission", 2018, tt="tt9000001"),
    film("Q9002", "Big Film Two", 2019, tt="tt9000002", us=date(2019, 5, 3)),
    film("Q9003", "Big Film", 2019, tt="tt9000003"),  # a different number: never Big Film Two
    film("Q9004", "Big Film Two", 1990, tt="tt9000004"),  # too early
    film("Q9005", "Stars and Stripes", 2020, tt="tt9000005"),
    film("Q9006", "The Gift", 2015, tt="tt9000006", sitelinks=5),
    film("Q9007", "The Gift", 2015, tt="tt9000007", sitelinks=6),
    film("Q7001", "Twin", 2016, tt="tt7000001", boms=["twina"]),
    film("Q1939", "Gone with the Wind", 1939, tt="tt0031381", sitelinks=80, us=date(1939, 12, 15)),
    film("Q8000", "No IMDb Film", 2005, boms=["noimdb"]),
    film("Q8100", "Stitched Film", 2016, tt="tt8100000", boms=["stitched"]),
    film("Q8101", "Stitched Film", 2016, tt="tt8100001"),
    film("Q8200", "Paper Moon Rising", 2017, tt="tt8200000", us=date(2017, 3, 3), sitelinks=40),
    film("Q8201", "Paper Moon Rising", 2017, tt="tt8200001", other=date(2016, 9, 1), sitelinks=1),
    film("Q1680", "Born to Be Wild", 2011, tt="tt1680059"),
    film("Q8300", "Split A", 2001, tt="tt8300000", boms=["splita"]),
    film("Q8301", "Split B", 2001, tt="tt8300001", boms=["splitb"]),
]


def rel(rid, title, first, *, tid=None, key=None, rl=None, rerelease=False, release_date=None, label=None,
        group_source="auto", source=None):
    key = key or rid.split(":", 1)[1]
    return {
        "release_id": rid, "title_id": tid or f"bb_{key.lower()}", "label": label, "release_date": release_date,
        "source_key": key, "source": source or ("bom_weekend" if rid.startswith("bom:") else "stat695"),
        "title": title, "distributor": "Dist", "genres": None, "mpaa": None, "first_weekend": first,
        "last_weekend": first + timedelta(weeks=4), "weekends": 5, "is_rerelease": rerelease,
        "rerelease_reason": "title_keyword" if rerelease else None, "parent_release_id": None,
        "group_source": group_source, "bom_release_id": rl if rl else (key if rid.startswith("bom:") else None),
    }


RELEASES = [
    rel("legacy:titanic", "Titanic", date(1997, 12, 21), release_date=date(1997, 12, 19)),
    rel("legacy:titanic3d", "Titanic (3D)", date(2012, 4, 8), tid="bb_titanic", rerelease=True, label="2012 3D"),
    rel("bom:rl1", "Titanic", date(2023, 2, 12), rerelease=True, label="2023 Re-release"),
    rel("bom:rl2", "Rogue Mission", date(2018, 3, 4)),
    rel("bom:rl3", "Big Film Two", date(2019, 5, 5)),
    rel("bom:rl4", "Starz & Stripes", date(2020, 7, 5)),
    rel("bom:rl5", "The Gift", date(2015, 8, 9)),
    rel("legacy:twina", "Twin", date(2016, 6, 5)),
    rel("bom:rl6", "Twin", date(2017, 6, 4)),
    rel("bom:rl7", "Overridden", date(2021, 1, 3)),
    rel("bom:rl8", "Gone with the Wind", date(2019, 3, 3), rerelease=True, label="2019 Re-release"),
    rel("legacy:noimdb", "No IMDb Film", date(2005, 4, 3)),
    rel("legacy:stitched", "Stitched Film", date(2016, 12, 4), rl="rl9"),
    rel("bom:rl10", "Paper Moon Rising", date(2017, 3, 5)),
    rel("legacy:borntobewildimax", "Born to Be Wild (IMAX)", date(2011, 4, 10), tid="tt1680059",
        group_source="manual"),
    rel("legacy:splita", "Split A", date(2001, 1, 7), tid="bb_split"),
    rel("legacy:splitb", "Split B", date(2001, 1, 14), tid="bb_split"),
    rel("legacy:unknown", "Nothing Like It", date(1999, 1, 3)),
]
PAGES = {"rl2": "tt9000001", "rl9": "tt8100001", "rl404": "tt0000404"}
OVERRIDES = {"rl7": {"source_key": "rl7", "title_id": "tt0000007", "wikidata_qid": "Q7", "release_label": None,
                     "source": "Wikidata Q7", "source_url": None, "notes": None}}


@pytest.fixture(scope="module")
def films(tmp_path_factory):
    path = tmp_path_factory.mktemp("wd") / "wikidata_films.parquet"
    wd.merge_items([{**f, "dates": list(f["dates"])} for f in FILMS]).write_parquet(path)
    return match.load_films(path)


@pytest.fixture(scope="module")
def result(films):
    rels = [{**r, "gross": 1_000_000 * (i + 1)} for i, r in enumerate(RELEASES)]
    return match.match_releases(rels, films, PAGES, OVERRIDES)


def test_norm_and_numbers():
    assert match.norm("The Amélie & Co.") == "amelie and co"
    assert match.norm("Ocean's Eleven") == "oceans eleven"
    assert match.numbers(match.norm("Rocky III")) == (3,) == match.numbers("rocky 3")
    assert match.numbers("big film") == ()
    assert match.base_title("Godzilla (2014)") == ("godzilla", 2014)
    assert match.base_title("Titanic (3D)") == ("titanic", None)
    assert match.base_title("Jaws (Re-issue)") == ("jaws", None)
    assert match.own_title("Jaws 3-D") == "jaws 3 d"
    assert match.own_title("Godzilla (2014)") == "godzilla"


@pytest.mark.parametrize("rid, method, title_id", [
    ("legacy:titanic", "p1237", "tt0120338"),
    ("legacy:titanic3d", "group", "tt0120338"),
    ("bom:rl1", "rerelease_title", "tt0120338"),
    ("bom:rl2", "release_page", "tt9000001"),
    ("bom:rl3", "title_year", "tt9000002"),
    ("bom:rl4", "fuzzy", "tt9000005"),
    ("bom:rl5", "unmatched", "bb_rl5"),  # two films called The Gift in 2015, near-equal
    ("legacy:twina", "p1237", "tt7000001"),
    ("bom:rl6", "unmatched", "bb_rl6"),  # the only Twin is already the 2016 release's
    ("bom:rl7", "override", "tt0000007"),
    ("bom:rl8", "rerelease_wikidata", "tt0031381"),
    ("legacy:noimdb", "p1237", "bb_q8000"),
    ("legacy:stitched", "release_page", "tt8100001"),  # the page beats P1237
    ("bom:rl10", "title_year", "tt8200000"),  # the US date and sitelinks break the tie
    ("legacy:borntobewildimax", "manual_group", "tt1680059"),
    ("legacy:unknown", "unmatched", "bb_unknown"),
])
def test_methods(result, rid, method, title_id):
    a = result.assign[rid]
    assert (a.method, a.title_id) == (method, title_id)


def test_qids_and_notes(result):
    assert result.assign["legacy:titanic3d"].qid == "Q44578"
    assert result.assign["bom:rl7"].qid == "Q7"
    assert result.assign["legacy:borntobewildimax"].qid == "Q1680"
    n = result.notes
    assert n["release_page_vs_p1237"][0].startswith("legacy:stitched")
    assert n["group_conflicts"] == ["group bb_split: legacy:splita -> tt8300000 (p1237); "
                                    "legacy:splitb -> tt8300001 (p1237)"]
    assert result.outcomes["bom:rl5"].why == "ambiguous"
    assert [c.qid for c in result.outcomes["bom:rl5"].candidates] == ["Q9007", "Q9006"]
    assert result.outcomes["bom:rl6"].why.startswith("only films claimed by other releases (Q7001")


def test_release_page_tt_missing_from_wikidata_is_noted(films):
    r = rel("bom:rl404", "Lost Page Film", date(2020, 1, 5))
    res = match.match_releases([{**r, "gross": 1}], films, PAGES, {})
    assert res.assign["bom:rl404"].method == "unmatched"
    assert res.notes["release_page_tt_not_on_wikidata"] == ["bom:rl404 'Lost Page Film': rl404 -> tt0000404"]


def test_bigger_release_claims_a_film_first(films):
    small = rel("bom:rl20", "Rogue Mission", date(2018, 3, 4))
    big = rel("bom:rl21", "Rogue Mission", date(2018, 3, 11))
    res = match.match_releases([{**small, "gross": 10}, {**big, "gross": 1000}], films, {}, {})
    assert res.assign["bom:rl21"].title_id == "tt9000001"
    assert res.assign["bom:rl20"].method == "unmatched"


def _index(tmp_path, films_):
    path = tmp_path / "wikidata_films.parquet"
    wd.merge_items([{**f, "dates": list(f["dates"])} for f in films_]).write_parquet(path)
    return match.load_films(path)


# A re-release's own Mojo id can sit on a version item with no IMDb id (Q10382726 "Titanic 3D").
VERSION = film("Q10382726", "Titanic 3D", 2012, boms=["titanic3d"], sitelinks=2)


def test_rerelease_on_a_version_item_joins_its_film(tmp_path):
    films_ = _index(tmp_path, [*FILMS, VERSION])
    grouped = rel("legacy:titanic3d", "Titanic 3D", date(2012, 4, 8), tid="bb_titanic", rerelease=True)
    alone = {**grouped, "release_id": "legacy:titanic3dx", "title_id": "bb_titanic3dx", "source_key": "titanic3d"}
    rels = [{**rel("legacy:titanic", "Titanic", date(1997, 12, 21)), "gross": 600}, {**grouped, "gross": 50},
            {**alone, "gross": 40}]
    res = match.match_releases(rels, films_, {}, {})
    assert (res.assign["legacy:titanic3d"].method, res.assign["legacy:titanic3d"].title_id) == ("group", "tt0120338")
    assert (res.assign["legacy:titanic3dx"].method, res.assign["legacy:titanic3dx"].title_id) == (
        "rerelease_title", "tt0120338")
    assert res.notes["p1237_version_items"][0] == "legacy:titanic3d 'Titanic 3D': titanic3d -> Q10382726"
    assert "group_conflicts" not in res.notes


def test_version_item_is_the_last_resort(tmp_path):
    films_ = _index(tmp_path, [VERSION])
    r = rel("legacy:titanic3d", "Titanic 3D", date(2012, 4, 8), rerelease=True)
    res = match.match_releases([{**r, "gross": 50}], films_, {}, {})
    assert (res.assign["legacy:titanic3d"].method, res.assign["legacy:titanic3d"].title_id) == ("p1237", "bb_q10382726")


JAWS = [film("Q189", "Jaws", 1975, tt="tt0073195", us=date(1975, 6, 20), sitelinks=80),
        film("Q9900", "Jaws", 2024, tt="tt9900000")]  # a same-titled film from the year it charted


def test_late_runs_match_on_the_opening_their_weeks_counter_implies(tmp_path):
    films_ = _index(tmp_path, [*FILMS, *JAWS,
                               film("Q501", "Shrek 2", 2004, tt="tt0298148", boms=["shrek2"], us=date(2004, 5, 19))])
    jaws = rel("bom:rl30", "Jaws", date(2024, 12, 29))
    shrek = rel("bom:rl31", "Shrek 2", date(2024, 12, 29))
    rels = [{**rel("legacy:shrek2", "Shrek 2", date(2004, 5, 23)), "gross": 441_220_800},
            {**jaws, "gross": 260_696_045, "opened": date(1975, 6, 22)},
            {**shrek, "gross": 441_550_292, "opened": date(2004, 5, 23)}]
    res = match.match_releases(rels, films_, {}, {})
    assert (res.assign["bom:rl30"].method, res.assign["bom:rl30"].title_id) == ("title_year", "tt0073195")
    # Shrek 2 is claimed by its first run, which this one continues: it joins it like a re-release.
    assert (res.assign["bom:rl31"].method, res.assign["bom:rl31"].title_id) == ("rerelease_title", "tt0298148")
    assert [n.split(":")[0] for n in res.notes["late_runs"]] == ["bom", "bom"]
    assert res.notes["late_runs"][0].startswith("bom:rl30 'Jaws': opened 1975-06-22 by its weeks counter")
    # Without the counter, the 2024 chart date picks the 2024 film.
    plain = match.match_releases([{**jaws, "gross": 1}], films_, {}, {})
    assert plain.assign["bom:rl30"].title_id == "tt9900000"


def test_rereleases_join_the_film_of_their_own_title(tmp_path):
    # Box Office Mojo's Jaws re-releases (2020, 2022, 2025) came after Jaws 3-D (1983) but before
    # the 1975 original's late run first charted (2024-12-29). They are Jaws's, not Jaws 3-D's.
    films_ = _index(tmp_path, [*FILMS, *JAWS, film("Q1199837", "Jaws 3-D", 1983, tt="tt0085750", boms=["jaws3d"]),
                               film("Q8400", "Ocean Wonders 3D", 2010, tt="tt8400000", boms=["oceanwonders3d"])])
    rels = [{**rel("legacy:jaws3d", "Jaws 3-D", date(1983, 7, 24)), "gross": 39_230_274},
            {**rel("bom:rl30", "Jaws", date(2024, 12, 29)), "gross": 260_696_045, "opened": date(1975, 6, 22)},
            *({**rel(rid, "Jaws", first, rerelease=True), "gross": 1000}
              for rid, first in (("bom:rl32", date(2020, 6, 21)), ("bom:rl33", date(2022, 9, 4)),
                                 ("bom:rl34", date(2025, 8, 31)))),
            # A 3D-only original still gets its plain re-release.
            {**rel("legacy:oceanwonders3d", "Ocean Wonders 3D", date(2010, 2, 14)), "gross": 5000},
            {**rel("bom:rl35", "Ocean Wonders", date(2020, 2, 16), rerelease=True), "gross": 100}]
    res = match.match_releases(rels, films_, {}, {})
    got = {rid: (a.method, a.title_id) for rid, a in res.assign.items()}
    assert got["legacy:jaws3d"] == ("p1237", "tt0085750")
    assert got["bom:rl30"] == ("title_year", "tt0073195")
    for rid in ("bom:rl32", "bom:rl33", "bom:rl34"):
        assert got[rid] == ("rerelease_title", "tt0073195"), rid
    assert got["bom:rl35"] == ("rerelease_title", "tt8400000")


def test_late_runs_of_claimed_films_join_the_run_that_opened_then(tmp_path):
    # Wikidata's "Backside to the Future" (Q139766422, 1986, based on Q91540) is a 90 fuzzy match
    # for "Back to the Future". It must not take the 1985 film's late run on the 2024-12-29 chart.
    films_ = _index(tmp_path, [
        film("Q91540", "Back to the Future", 1985, tt="tt0088763", boms=["backtothefuture"], us=date(1985, 7, 3)),
        film("Q139766422", "Backside to the Future", 1986, tt="tt0149767"),
        film("Q1", "Dune", 1984, tt="tt0087182", boms=["dune"], us=date(1984, 12, 14)),
        film("Q2", "Dune", 2021, tt="tt1160419", us=date(2021, 10, 22)),
        film("Q3", "Small Run", 2010, tt="tt3000000", us=date(2010, 3, 5)),
    ])
    rels = [{**rel("legacy:backtothefuture", "Back to the Future", date(1985, 7, 7)), "gross": 202_484_520},
            {**rel("bom:rl40", "Back to the Future", date(2024, 12, 29)), "gross": 212_326_307,
             "opened": date(1985, 7, 7)},
            {**rel("bom:rl41", "Back to the Future", date(2025, 11, 2), rerelease=True), "gross": 7_890_200},
            {**rel("legacy:dune", "Dune", date(1984, 12, 16)), "gross": 30_925_690},
            {**rel("bom:rl42", "Dune", date(2021, 10, 24)), "gross": 108_327_830},
            {**rel("bom:rl43", "Dune", date(2024, 12, 29)), "gross": 31_439_560, "opened": date(1984, 12, 16)},
            # A late run bigger than its own first run doesn't take the film from it.
            {**rel("bom:rl44", "Small Run", date(2010, 3, 7)), "gross": 10},
            {**rel("bom:rl45", "Small Run", date(2024, 12, 29)), "gross": 99, "opened": date(2010, 3, 7)}]
    res = match.match_releases(rels, films_, {}, {})
    got = {rid: (a.method, a.title_id) for rid, a in res.assign.items()}
    assert got["bom:rl40"] == ("rerelease_title", "tt0088763")
    assert got["bom:rl41"] == ("rerelease_title", "tt0088763")
    assert got["bom:rl42"] == ("title_year", "tt1160419")
    assert got["bom:rl43"] == ("rerelease_title", "tt0087182")
    assert got["bom:rl44"] == ("title_year", "tt3000000")
    assert got["bom:rl45"] == ("rerelease_title", "tt3000000")


def test_late_runs_from_snapshots():
    snaps = pl.DataFrame({
        "release_id": ["bom:rl24217089", "bom:rl24217089", "bom:new", "bom:expanded", "bom:none"],
        "weekend_end": [date(2024, 12, 29), date(2025, 1, 5), date(2024, 12, 29), date(2024, 12, 29),
                        date(2024, 12, 29)],
        "weeks": [1076, 1077, 1, 30, None],
    })
    assert match.late_runs(snaps) == {"bom:rl24217089": date(2004, 5, 23)}


def test_late_run_originals_are_dated_by_their_opening(repo):
    # Box Office Mojo's 1975 Jaws first charts here on 2024-12-29, its week 2585. With no release
    # page to date it (a build from an empty cache), it's still a 1975 film: the opening its weeks
    # counter implies, which Wikidata's US date is close to. A late run with no US date near its
    # opening (a 1984 film whose US run opened in 2014) keeps the counter's year, not the year it
    # first charted here.
    build_dir = repo / "data" / "build"
    build_dir.mkdir(parents=True)
    wd.merge_items([{**f, "dates": list(f["dates"])} for f in [*JAWS, film("Q8500", "Old Doc", 1984)]]).write_parquet(
        build_dir / "wikidata_films.parquet")
    runs = [(rel("bom:rl30", "Jaws", date(2024, 12, 29)), date(1975, 6, 22)),
            (rel("bom:rl50", "Old Doc", date(2018, 9, 23)), date(2014, 6, 8))]
    releases = pl.DataFrame([r for r, _ in runs], schema=build.PUBLISHED_RELEASE_SCHEMA)
    snaps = pl.DataFrame([{"weekend_end": r["first_weekend"], "release_id": r["release_id"], "title_id": r["title_id"],
                           "rank": 13, "weekend_gross": 10, "theaters": None, "total_gross": 1_000_000,
                           "weeks": (r["first_weekend"] - opened).days // 7 + 1, "source": "bom_weekend",
                           "capture_url": None, "is_estimate": False} for r, opened in runs], schema=SNAPSHOT_SCHEMA)
    out = match.apply(releases, snaps, build_dir, repo / "data" / "manual", log=lambda *a: None)
    tid = dict(zip(out.releases["release_id"].to_list(), out.releases["title_id"].to_list()))
    t = {x["title_id"]: x for x in out.titles.to_dicts()}
    assert tid["bom:rl30"] == "tt0073195"
    assert (t["tt0073195"]["year"], t["tt0073195"]["release_date"]) == (1975, date(1975, 6, 20))
    assert (t[tid["bom:rl50"]]["year"], t[tid["bom:rl50"]]["release_date"]) == (2014, None)


# --- apply: the published tables ----------------------------------------------------------

def test_apply_rewrites_title_ids_and_builds_titles(repo, films):
    build_dir = repo / "data" / "build"
    build_dir.mkdir(parents=True)
    wd.merge_items([{**f, "dates": list(f["dates"])} for f in FILMS]).write_parquet(build_dir / "wikidata_films.parquet")
    pl.DataFrame({"rl_id": list(PAGES), "tt_id": list(PAGES.values())}).write_parquet(
        build_dir / "bom_release_pages.parquet")
    manual = repo / "data" / "manual"
    (manual / "id_overrides.csv").write_text(
        "source_key,title_id,wikidata_qid,release_label,source,source_url,notes\n"
        "rl7,tt0000007,Q7,,Wikidata Q7 (test),,\n"
        "rl3,tt9000002,,2019 Director's Cut,Wikidata Q9002 (test),,\n", encoding="utf-8")
    releases = pl.DataFrame(RELEASES, schema=build.PUBLISHED_RELEASE_SCHEMA)
    snaps = pl.DataFrame([{"weekend_end": r["first_weekend"], "release_id": r["release_id"], "title_id": r["title_id"],
                           "rank": 1, "weekend_gross": 10, "theaters": 1, "total_gross": 1_000_000 * (i + 1),
                           "weeks": 1, "source": "stat695", "capture_url": None, "is_estimate": False}
                          for i, r in enumerate(RELEASES)], schema=SNAPSHOT_SCHEMA)
    out = match.apply(releases, snaps, build_dir, manual, log=lambda *a: None)

    r = {x["release_id"]: x for x in out.releases.to_dicts()}
    assert r["bom:rl1"]["title_id"] == "tt0120338" and r["bom:rl1"]["match_method"] == "rerelease_title"
    assert (r["bom:rl3"]["label"], r["bom:rl3"]["is_rerelease"], r["bom:rl3"]["rerelease_reason"]) == (
        "2019 Director's Cut", True, "manual")
    s = dict(zip(out.snapshots["release_id"].to_list(), out.snapshots["title_id"].to_list()))
    assert s == {k: v["title_id"] for k, v in r.items()}

    t = {x["title_id"]: x for x in out.titles.to_dicts()}
    assert set(t) == {v["title_id"] for v in r.values()}
    assert (t["tt0120338"]["title"], t["tt0120338"]["year"], t["tt0120338"]["release_date"],
            t["tt0120338"]["wikidata_qid"]) == ("Titanic", 1997, date(1997, 12, 19), "Q44578")
    # Only a re-release charted: Wikidata's label and US date.
    assert (t["tt0031381"]["title"], t["tt0031381"]["year"], t["tt0031381"]["release_date"]) == (
        "Gone with the Wind", 1939, date(1939, 12, 15))
    # An original with no release date of its own takes the US date when it's close.
    assert t["tt8200000"]["release_date"] == date(2017, 3, 3)
    assert t["bb_unknown"]["wikidata_qid"] is None and t["bb_unknown"]["year"] == 1999

    rep = json.loads((build_dir / "match_report.json").read_text())
    assert rep["films_loaded"] == len(FILMS) and rep["releases"] == len(RELEASES)
    unmatched = {x["release_id"] for x in rep["top_unmatched"]}
    assert unmatched == {"bom:rl5", "bom:rl6", "legacy:noimdb", "legacy:unknown"}
    gross = {x["release_id"]: (i + 1) * 1_000_000 for i, x in enumerate(RELEASES)}
    assert rep["gross_matched_tt"] == sum(g for k, g in gross.items() if k not in unmatched)
    assert rep["by_method"]["override"]["releases"] == 2
    assert rep["ambiguous"][0]["release_id"] == "bom:rl5"
    with (build_dir / "match_report.csv").open(encoding="utf-8") as fh:
        rows = {x["release_id"]: x for x in csv.DictReader(fh)}
    assert rows["bom:rl5"]["why"] == "ambiguous" and "Q9007" in rows["bom:rl5"]["candidates"]
    assert pl.read_parquet(build_dir / "match.parquet").height == len(RELEASES)


def test_baseline_titles_join_and_stand_alone(films):
    rels = [{**RELEASES[0], "title_id": "tt0120338", "gross": 5}]
    assign = {"legacy:titanic": match.Assign("tt0120338", "Q44578", "p1237")}
    baseline = [
        {"title": "Titanic", "release_year": 1997, "wikidata_qid": None, "title_id": "tt0120338", "gross_usd": 1.0,
         "as_of": date(1981, 12, 31), "is_rental": False, "source": "Test source", "source_url": None, "notes": None},
        {"title": "Gone with the Wind", "release_year": 1939, "wikidata_qid": "Q1939", "title_id": None,
         "gross_usd": 2.0, "as_of": date(1981, 12, 31), "is_rental": True, "source": "Test", "source_url": "https://x.y",
         "notes": None},
    ]
    t = {x["title_id"]: x for x in match.build_titles(rels, assign, films, baseline).to_dicts()}
    assert t["tt0120338"]["pre1982_baseline_gross"] == 1.0 and t["tt0120338"]["baseline_is_rental"] is False
    assert (t["tt0031381"]["title"], t["tt0031381"]["year"], t["tt0031381"]["baseline_is_rental"],
            t["tt0031381"]["baseline_source"]) == ("Gone with the Wind", 1939, True, "Test (https://x.y)")
