from __future__ import annotations

import json
import re
from datetime import date
from urllib.parse import parse_qs, urlsplit

import httpx
import polars as pl
import pytest

from boffo_etl import paths
from boffo_etl.fetch import FetchDisabledError, Fetcher
from boffo_etl.sources import wikidata as wd

TODAY = date(2026, 11, 7)
E = "http://www.wikidata.org/entity/"


def item(qid, label=None, *, tts=(), boms=(), dates=(), aliases=(), sitelinks=0, mul=None):
    row = {"item": {"type": "uri", "value": E + qid}, "sitelinks": {"type": "literal", "value": str(sitelinks)},
           "imdbs": {"type": "literal", "value": "|".join(tts)}, "boms": {"type": "literal", "value": "|".join(boms)},
           "dates": {"type": "literal", "value": "|".join(dates)},
           "aliases": {"type": "literal", "value": "|".join(aliases)}}
    if label:
        row["labelEn"] = {"type": "literal", "value": label}
    if mul:
        row["labelMul"] = {"type": "literal", "value": mul}
    return row


class FakeQLever:
    """Answers the snapshot's queries by the 'what' in their marker comment."""

    def __init__(self) -> None:
        self.pages: dict[str, list[dict]] = {}  # "P1237", "films 2015", ... -> rows
        self.by_tt: dict[str, dict] = {}  # P345 lookups
        self.fail: set[str] = set()  # stamps answered with HTTP 503
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        assert urlsplit(url).hostname == "qlever.dev"
        query = parse_qs(urlsplit(url).query)["query"][0]
        self.requests.append(query.splitlines()[0])
        m = re.match(r"^# BoxOfficeBozo Wikidata snapshot (\d{4}-\d{2}) \((.+)\)$", query.splitlines()[0])
        assert m, query[:80]
        if m[1] in self.fail:
            return httpx.Response(503, text="<html>down</html>")
        what = m[2]
        if what.startswith("P345 "):
            tts = re.findall(r'"(tt\d+)"', query)
            rows = [self.by_tt[t] for t in tts if t in self.by_tt]
        else:
            rows = self.pages.get(what, [])
        body = {"head": {"vars": ["item"]}, "results": {"bindings": rows}}
        return httpx.Response(200, json=body, headers={"content-type": "application/sparql-results+json"})

    def fetcher(self) -> Fetcher:
        return Fetcher(httpx.Client(transport=httpx.MockTransport(self)), min_interval=0, sleep=lambda s: None)


# --- queries -------------------------------------------------------------------

def test_snapshot_pages_cover_every_year_once():
    pages = wd.snapshot_pages("2026-11")
    assert [p.what for p in pages[:3]] == ["P1237", "films 1890-1909", "films 1910"]
    assert pages[-1].what == "films 2027"
    assert len(pages) == 2 + (2027 - 1910 + 1)
    assert len({p.url for p in pages}) == len(pages)
    assert all(p.url.startswith("https://qlever.dev/api/wikidata?query=") for p in pages)
    q = parse_qs(urlsplit(pages[5].url).query)["query"][0]
    assert q.startswith("# BoxOfficeBozo Wikidata snapshot 2026-11 (films 1913)\nPREFIX wd:")
    assert "YEAR(?d0) >= 1913 && YEAR(?d0) < 1914" in q and "wd:Q11424" in q
    # A new month is a new set of URLs (refetched); the same month is cached.
    assert {p.url for p in wd.snapshot_pages("2026-12")}.isdisjoint({p.url for p in pages})


def test_imdb_query_rejects_non_tt_ids():
    q = wd.imdb_query(["tt0120338", "tt0499549"], "2026-11")
    assert 'VALUES ?i0 { "tt0120338" "tt0499549" }' in q
    with pytest.raises(ValueError):
        wd.imdb_query(['tt1" } . ?x ?y ?z . {', "tt0120338"], "2026-11")


def test_stamps():
    assert wd.stamp_of(TODAY) == "2026-11"
    assert wd.previous_stamps(date(2026, 2, 3), 3) == ["2026-01", "2025-12", "2025-11"]


# --- parsing ---------------------------------------------------------------------

def test_parse_date():
    assert wd.parse_date("2015-11-20T00:00:00Z/11/Q30") == {
        "date": date(2015, 11, 20), "year": 2015, "precision": 11, "place": "Q30"}
    assert wd.parse_date("2014-01-01T00:00:00Z/9/") == {"date": None, "year": 2014, "precision": 9, "place": None}
    assert wd.parse_date("1990-01-01T00:00:00Z/8/") is None  # a decade
    assert wd.parse_date("-0500-01-01T00:00:00Z/9/") is None
    assert wd.parse_date("garbage") is None


def test_parse_items():
    rows = wd.parse_sparql_json(json.dumps({"head": {"vars": []}, "results": {"bindings": [
        item("Q1", "Big Film", tts=("tt0000002", "tt0000001", "nm123"), boms=("BigFilm.htm", "bigfilm"),
             aliases=("Big Film", "The Big Film"), dates=("2015-11-20T00:00:00Z/11/Q30", "2015-01-01T00:00:00Z/9/"),
             sitelinks=12),
        item("Q2", None, mul="Amélie"),
        {"item": {"type": "uri", "value": "http://example.org/x"}},
    ]}}).encode())
    films = wd.parse_items(rows, "films 2015")
    assert [f["qid"] for f in films] == ["Q1", "Q2"]
    f = films[0]
    assert f["tt"] == "tt0000001" and f["tts"] == ["tt0000001", "tt0000002"]
    assert f["bom_ids"] == ["bigfilm"] and f["aliases"] == ["The Big Film"] and f["sitelinks"] == 12
    assert [d["year"] for d in f["dates"]] == [2015, 2015] and f["dates"][0]["date"] is None
    assert films[1]["label"] == "Amélie" and films[1]["tt"] is None


def test_validate_rejects_outage_pages():
    with pytest.raises(ValueError):
        wd.validate_sparql(b"<html>Service unavailable</html>")
    with pytest.raises(ValueError):
        wd.validate_sparql(b'{"exception": "timed out"}')
    wd.validate_sparql(b'{"head": {"vars": []}, "results": {"bindings": []}}')


# --- the step ----------------------------------------------------------------------

def world() -> FakeQLever:
    q = FakeQLever()
    q.pages["P1237"] = [
        item("Q44578", "Titanic", tts=("tt0120338",), boms=("titanic", "titanic3d"), sitelinks=90),
        item("Q900", "Dup A", tts=("tt0000900",), boms=("dup",), sitelinks=1),
        item("Q901", "Dup B", tts=("tt0000901",), boms=("dup",), sitelinks=2),
    ]
    q.pages["films 1997"] = [item("Q44578", "Titanic", tts=("tt0120338",), boms=("titanic",), sitelinks=90,
                                  aliases=("Titanic 3D",), dates=("1997-12-19T00:00:00Z/11/Q30",))]
    q.pages["films 2015"] = [item("Q10", "Two Years", tts=("tt0000010",), dates=("2015-09-01T00:00:00Z/11/Q38",))]
    q.pages["films 2016"] = [item("Q10", "Two Years", tts=("tt0000010",), dates=("2016-03-04T00:00:00Z/11/Q30",))]
    q.by_tt["tt7000001"] = item("Q7001", "Paged Film", tts=("tt7000001",))
    return q


def test_ingest_merges_items_and_looks_up_release_page_ids(repo, monkeypatch):
    monkeypatch.setenv("BOFFO_FETCH", "1")
    q = world()
    snap = wd.ingest(q.fetcher(), TODAY, ["tt0120338", "tt7000001", "tt7999999"], log=lambda *a: None)
    films = {r["qid"]: r for r in snap.films.to_dicts()}
    assert set(films) == {"Q44578", "Q900", "Q901", "Q10", "Q7001"}
    assert films["Q44578"]["bom_ids"] == ["titanic", "titanic3d"]  # the P1237 list and the 1997 page merged
    assert films["Q44578"]["aliases"] == ["Titanic 3D"] and films["Q44578"]["origin"] == "P1237"
    assert [d["year"] for d in films["Q10"]["dates"]] == [2015, 2016]
    assert films["Q7001"]["origin"] == "P345 lookup"
    r = snap.report
    assert r["snapshot"] == "2026-11" and r["stale_reason"] is None
    assert r["release_page_tt_lookup"] == {"asked": 2, "found": 1, "error": None}
    assert r["bom_ids_on_several_items"] == ["dup: Q900, Q901"]
    assert r["items_with_bom_id"] == 3
    assert len(q.requests) == len(wd.snapshot_pages("2026-11")) + 1

    # Cached: a second run makes no requests.
    q2 = world()
    wd.ingest(q2.fetcher(), TODAY, ["tt0120338", "tt7000001", "tt7999999"], log=lambda *a: None)
    assert q2.requests == []


def test_falls_back_to_the_newest_complete_snapshot(repo, monkeypatch):
    monkeypatch.setenv("BOFFO_FETCH", "1")
    wd.ingest(world().fetcher(), date(2026, 10, 15), [], log=lambda *a: None)  # October, complete
    q = world()
    q.fail.add("2026-11")
    snap = wd.ingest(q.fetcher(), TODAY, [], log=lambda *a: None)
    assert snap.report["snapshot"] == "2026-10" and "503" in snap.report["stale_reason"]
    assert snap.films.height == 4
    assert snap.report["pruned_cache_entries"] == 0  # October is kept until November is complete


def test_complete_snapshot_prunes_older_ones(repo, monkeypatch):
    monkeypatch.setenv("BOFFO_FETCH", "1")
    wd.ingest(world().fetcher(), date(2026, 10, 15), [], log=lambda *a: None)
    other = repo / "data/raw/http/qlever.dev/unrelated.json"
    other.write_text("{}")
    snap = wd.ingest(world().fetcher(), TODAY, [], log=lambda *a: None)
    assert snap.report["pruned_cache_entries"] == len(wd.snapshot_pages("2026-10"))
    f = world().fetcher()
    assert not any(f.is_cached(p.url) for p in wd.snapshot_pages("2026-10"))
    assert all(f.is_cached(p.url) for p in wd.snapshot_pages("2026-11"))
    assert other.exists()


def test_offline_without_a_cache_raises(repo):
    with pytest.raises(FetchDisabledError):
        wd.ingest(world().fetcher(), TODAY, [], log=lambda *a: None)


def test_run_writes_outputs(repo, monkeypatch):
    monkeypatch.setenv("BOFFO_FETCH", "1")
    build = paths.data_build()
    build.mkdir(parents=True)
    pl.DataFrame({"rl_id": ["rl1", "rl2"], "tt_id": ["tt7000001", None]}).write_parquet(build / "bom_release_pages.parquet")
    wd.run(world().fetcher(), TODAY)
    films = pl.read_parquet(build / "wikidata_films.parquet")
    assert "Q7001" in films["qid"].to_list()
    assert json.loads((build / "wikidata_report.json").read_text())["release_page_tt_lookup"]["found"] == 1
