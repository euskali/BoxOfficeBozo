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
