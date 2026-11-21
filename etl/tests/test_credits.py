from __future__ import annotations

import json
import re
import time
from datetime import date
from urllib.parse import parse_qs, urlsplit

import httpx
import polars as pl
import pytest

from boffo_etl import paths
from boffo_etl.fetch import FetchDisabledError, Fetcher
from boffo_etl.sources import credits as cr
from boffo_etl.sources import wikidata as wd

NOV, DEC = date(2026, 11, 21), date(2026, 12, 7)
E = "http://www.wikidata.org/entity/"
LATER = float("inf")


def claim(prop, qid=None, *, rank="normal", ordinal=None, snaktype="value"):
    c = {"mainsnak": {"snaktype": snaktype, "property": prop}, "type": "statement", "rank": rank,
         "references": [{"snaks": {"P143": [{"snaktype": "value", "property": "P143"}]}}]}
    if snaktype == "value":
        c["mainsnak"]["datavalue"] = {"type": "wikibase-entityid",
                                      "value": {"entity-type": "item", "numeric-id": int(qid[1:]), "id": qid}}
    if ordinal is not None:
        c["qualifiers"] = {"P1545": [{"snaktype": "value", "property": "P1545",
                                      "datavalue": {"type": "string", "value": ordinal}}]}
    return c


def entity(qid, directors=(), cast=(), voices=()):
    claims = {"P31": [claim("P31", "Q11424")], "P345": [{"mainsnak": {"snaktype": "value", "property": "P345",
                                                                   "datavalue": {"type": "string", "value": "tt1"}}}]}
    for prop, items in (("P57", directors), ("P161", cast), ("P725", voices)):
        if items:
            claims[prop] = [i if isinstance(i, dict) else claim(prop, i) for i in items]
    return {"type": "item", "id": qid, "claims": claims}


class FakeWikidata:
    """The Wikidata API (wbgetentities) and QLever's people query, in memory."""

    def __init__(self) -> None:
        self.entities: dict[str, dict] = {}
        self.persons: dict[str, dict] = {}  # person -> {"en": ..., "mul": ..., "nm": ...}
        self.requests: list[tuple[str, tuple[str, ...]]] = []
        self.down: set[str] = set()

    def film(self, qid, **kw) -> None:
        self.entities[qid] = entity(qid, **kw)

    def person(self, qid, en=None, *, mul=None, nm=None) -> None:
        self.persons[qid] = {"en": en, "mul": mul, "nm": nm}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        host, query = urlsplit(url).hostname, parse_qs(urlsplit(url).query)
        if host in self.down:
            return httpx.Response(503, text="down")
        if host == "www.wikidata.org":
            ids = query["ids"][0].split("|")
            self.requests.append(("claims", tuple(ids)))
            ents = {i: self.entities.get(i, {"id": i, "missing": ""}) for i in ids}
            return httpx.Response(200, json={"entities": ents, "success": 1, "requestid": query["requestid"][0]})
        assert host == "qlever.dev"
        text = query["query"][0]
        films = re.findall(r"wd:(Q\d+)", cr.VALUES_RE.search(text)[1])
        self.requests.append(("people", tuple(films)))
        credited = {c["mainsnak"]["datavalue"]["value"]["id"] for f in films for p in cr.PROPS
                    for c in self.entities.get(f, {}).get("claims", {}).get(p, [])
                    if c["mainsnak"]["snaktype"] == "value"}
        rows = []
        for qid in sorted(credited & set(self.persons)):
            p = self.persons[qid]
            row = {"person": {"type": "uri", "value": E + qid},
                   "imdbs": {"type": "literal", "value": p["nm"] or ""}}
            if p["en"]:
                row["labelEn"] = {"type": "literal", "value": p["en"]}
            if p["mul"]:
                row["labelMul"] = {"type": "literal", "value": p["mul"]}
            rows.append(row)
        return httpx.Response(200, json={"head": {"vars": ["person"]}, "results": {"bindings": rows}},
                              headers={"content-type": "application/sparql-results+json"})

    def fetcher(self) -> Fetcher:
        return Fetcher(httpx.Client(transport=httpx.MockTransport(self)), min_interval=0, sleep=lambda s: None)


@pytest.fixture
def fake(repo, monkeypatch):
    monkeypatch.setenv("BOFFO_FETCH", "1")
    monkeypatch.setattr(cr, "CLAIMS_BATCH", 2)
    monkeypatch.setattr(cr, "PEOPLE_BATCH", 3)
    f = FakeWikidata()
    # Jaws: one director, cast in statement order.
    f.film("Q189505", directors=["Q8877"], cast=["Q216569", "Q313727", "Q181799"])
    # Toy Story: the cast is all voice actors (P725), with one stray P161 of unknown value.
    f.film("Q171048", directors=["Q269214"], cast=[claim("P161", snaktype="somevalue")],
           voices=["Q2263", "Q208408", "Q269890", "Q311068", "Q276181"])
    # Force Awakens: P1545 ordinals on the first three statements put them in their own order.
    f.film("Q6074", directors=["Q188137"],
           cast=[claim("P161", "Q108941", ordinal="3"), claim("P161", "Q81328", ordinal="1"),
                 claim("P161", "Q210447", ordinal="2"), "Q4678990",
                 claim("P161", "Q9999", rank="deprecated"), "Q4678990"])
    f.film("Q134773", directors=["Q187364"], cast=["Q2263", "Q180272"])
    for qid, name, nm in (("Q8877", "Steven Spielberg", "nm0000229"), ("Q2263", "Tom Hanks", "nm0000158"),
                          ("Q216569", "Roy Scheider", None), ("Q313727", "Robert Shaw", None),
                          ("Q181799", "Richard Dreyfuss", None), ("Q269214", "John Lasseter", "nm0005124"),
                          ("Q208408", "Tim Allen", None), ("Q269890", "Don Rickles", None),
                          ("Q311068", "Jim Varney", None), ("Q276181", "Wallace Shawn", None),
                          ("Q188137", "J. J. Abrams", None), ("Q108941", "Carrie Fisher", None),
                          ("Q81328", "Harrison Ford", None), ("Q210447", "Mark Hamill", None),
                          ("Q4678990", "Adam Driver", None), ("Q187364", "Robert Zemeckis", None),
                          ("Q180272", "Robin Wright", None)):
        f.person(qid, name, nm=nm)
    return f


FILMS = [cr.Film("tt2488496", "Q6074", "Star Wars: The Force Awakens", 936_662_225),
         cr.Film("tt0109830", "Q134773", "Forrest Gump", 330_252_182),
         cr.Film("tt0073195", "Q189505", "Jaws", 260_000_000),
         cr.Film("tt0114709", "Q171048", "Toy Story", 191_796_233)]


def _credits(result, title_id, role="actor"):
    return result.credits.filter((pl.col("title_id") == title_id) & (pl.col("role") == role)) \
        .sort("billing", nulls_last=True).select("person_id", "billing", "billing_source").rows()


# --- requests and answers ----------------------------------------------------------

def test_requests_carry_the_month_and_their_films():
    url = cr.claims_url(["Q189505", "Q171048"], "2026-11")
    assert url.startswith("https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=claims&ids=")
    assert cr.parse_request(url) == ("claims", "2026-11", ("Q189505", "Q171048"))
    people = cr.people_url(["Q189505", "Q171048"], "2026-11")
    q = parse_qs(urlsplit(people).query)["query"][0]
    assert q.startswith("# BoxOfficeBozo Wikidata credits 2026-11 (people Q189505+1)\nPREFIX wd:")
    assert "VALUES ?film { wd:Q189505 wd:Q171048 }" in q
    assert cr.parse_request(people) == ("people", "2026-11", ("Q189505", "Q171048"))
    assert cr.claims_url(["Q1"], "2026-12") != cr.claims_url(["Q1"], "2026-11")
    assert cr.parse_request(wd.snapshot_pages("2026-11")[0].url) is None  # M3's own queries aren't ours
    with pytest.raises(ValueError):
        cr.claims_url(["tt0073195"], "2026-11")


def test_reduce_keeps_the_credit_statements_in_order():
    raw = {"entities": {
        "Q6074": entity("Q6074", directors=["Q188137"],
                        cast=[claim("P161", "Q108941", ordinal="3"), claim("P161", snaktype="somevalue"),
                              claim("P161", "Q9999", rank="deprecated")]),
        "Q1": {"id": "Q1", "missing": ""},
        "Q500": {**entity("Q501", directors=["Q8877"]), "redirects": {"from": "Q500", "to": "Q501"}},
    }, "success": 1}
    body = json.dumps(raw).encode()
    cr.validate_claims(body)
    reduced = json.loads(cr.reduce_claims(body))["entities"]
    assert reduced["Q6074"] == {"id": "Q6074", "P57": [["Q188137", "normal", None]],
                                "P161": [["Q108941", "normal", "3"], [None, "normal", None], ["Q9999", "deprecated", None]],
                                "P725": []}
    assert reduced["Q1"]["missing"] is True
    assert reduced["Q500"]["id"] == "Q501" and reduced["Q500"]["P57"] == [["Q8877", "normal", None]]
    assert len(cr.reduce_claims(body)) < len(body) / 2


@pytest.mark.parametrize("body", [b"<html>busy</html>", b'{"error": {"code": "maxlag"}}', b'{"success": 1}'])
def test_unusable_api_answers_are_refused(body):
    with pytest.raises(ValueError):
        cr.validate_claims(body)


def test_billing_rules():
    rec = {"P57": [["Q1", "normal", None], ["Q1", "normal", None], [None, "normal", None]],
           "P161": [["Q10", "normal", None], ["Q11", "normal", "2"], ["Q12", "deprecated", "1"], ["Q13", "normal", "x"],
                    ["Q14", "preferred", "1"]],
           "P725": [["Q20", "normal", None]]}
    rows = cr.film_credits("tt1", rec)
    assert [(r["person_id"], r["role"], r["billing"], r["billing_source"]) for r in rows] == [
        ("Q1", "director", None, None),
        ("Q14", "actor", 1, "p1545"), ("Q11", "actor", 2, "p1545"),
        ("Q10", "actor", 3, "statement_order"), ("Q13", "actor", 4, "statement_order"),
        ("Q20", "actor", 5, "statement_order")]
    # The longer of the cast and voice lists leads: an animated film's voices, then its live action.
    voiced = cr.film_credits("tt2", {"P161": [["Q30", "normal", None]],
                                     "P725": [["Q31", "normal", None], ["Q30", "normal", None], ["Q32", "normal", None]]})
    assert [(r["person_id"], r["billing"]) for r in voiced] == [("Q31", 1), ("Q30", 2), ("Q32", 3)]


# --- the step --------------------------------------------------------------------

def test_fetches_biggest_films_first_and_builds_the_tables(fake):
    res = cr.ingest(fake.fetcher(), FILMS, NOV, LATER, log=lambda *a: None)
    assert fake.requests == [("claims", ("Q6074", "Q134773")), ("people", ("Q6074", "Q134773", "Q189505")),
                             ("claims", ("Q189505", "Q171048")), ("people", ("Q171048",))]
    assert _credits(res, "tt2488496") == [("Q81328", 1, "p1545"), ("Q210447", 2, "p1545"), ("Q108941", 3, "p1545"),
                                          ("Q4678990", 4, "statement_order")]
    assert _credits(res, "tt0114709")[0] == ("Q2263", 1, "statement_order")
    assert _credits(res, "tt0109830")[0] == ("Q2263", 1, "statement_order")
    assert _credits(res, "tt0073195", "director") == [("Q8877", None, None)]
    people = {r["person_id"]: r for r in res.people.to_dicts()}
    assert people["Q8877"] == {"person_id": "Q8877", "imdb_id": "nm0000229", "name": "Steven Spielberg"}
    assert set(people) == set(res.credits["person_id"])
    r = res.report
    assert (r["month"], r["month_complete"], r["films_with_statements"], r["films_from_older_month"]) == (
        "2026-11", True, 4, 0)
    assert r["voice_cast_films"] == 1 and r["films_with_director_share"] == 1.0
    assert r["films_with_top_billed_cast"] == 2  # Jaws has three cast here, Forrest Gump two
    assert r["billing_source"] == {"p1545": 3, "statement_order": 11}
    assert r["fetch"] == {"planned": 4, "done": 4, "stopped": None}
    # Only the credit statements are cached, and the meta file says so.
    metas = list((paths.data_raw() / "http" / "www.wikidata.org").glob("*.meta.json"))
    assert len(metas) == 2 and all(json.loads(m.read_text())["reduced"] for m in metas)


def test_same_month_reruns_use_the_cache_and_new_films_get_their_own_requests(fake):
    cr.ingest(fake.fetcher(), FILMS, NOV, LATER, log=lambda *a: None)
    fake.requests.clear()
    again = cr.ingest(fake.fetcher(), FILMS, NOV, LATER, log=lambda *a: None)
    assert fake.requests == [] and again.report["network_requests"] == 0
    fake.film("Q167726", directors=["Q8877"], cast=["Q51506"])
    more = [*FILMS[:2], cr.Film("tt0107290", "Q167726", "Jurassic Park", 357_067_947), *FILMS[2:]]
    res = cr.ingest(fake.fetcher(), more, NOV, LATER, log=lambda *a: None)
    assert fake.requests == [("claims", ("Q167726",)), ("people", ("Q167726",))]
    assert _credits(res, "tt0107290", "director") == [("Q8877", None, None)]


def test_an_unfinished_month_falls_back_to_the_last_and_prunes_it_once_complete(fake):
    cr.ingest(fake.fetcher(), FILMS, NOV, LATER, log=lambda *a: None)
    fake.requests.clear()
    # December, with the time budget already spent: November's answers stand in.
    stale = cr.ingest(fake.fetcher(), FILMS, DEC, time.monotonic() - 1, log=lambda *a: None)
    assert fake.requests == []
    assert stale.report["month_complete"] is False and stale.report["films_from_older_month"] == 4
    assert stale.report["fetch"]["stopped"] == "time budget" and stale.credits.height > 0
    assert {e.stamp for e in cr.cached_entries()} == {"2026-11"}
    fresh = cr.ingest(fake.fetcher(), FILMS, DEC, LATER, log=lambda *a: None)
    assert fresh.report["month_complete"] is True and fresh.report["pruned_cache_entries"] == 4
    assert {e.stamp for e in cr.cached_entries()} == {"2026-12"}
    assert fresh.credits.equals(stale.credits)


def test_a_failing_host_stops_fetching_but_what_is_cached_is_published(fake):
    fake.down.add("qlever.dev")
    res = cr.ingest(fake.fetcher(), FILMS, NOV, LATER, log=lambda *a: None)
    assert res.report["fetch"]["stopped"].startswith("error: ")
    assert res.report["films_with_statements"] == 2 and res.report["films_without_statements"] == 2
    assert res.people["name"].is_null().all()  # no names yet; the next run fetches them
    assert res.report["people_without_name"] == res.people.height


def test_offline_with_nothing_cached_skips_the_step(repo):
    with pytest.raises(FetchDisabledError):
        cr.ingest(FakeWikidata().fetcher(), FILMS, NOV, LATER, log=lambda *a: None)


def test_names_fall_back_to_mul_and_skip_bare_ids(fake):
    fake.person("Q216569", None, mul="Roy Scheider")
    fake.person("Q313727", "Q313727", mul="Robert Shaw")
    fake.person("Q181799", "Q181799")
    res = cr.ingest(fake.fetcher(), FILMS, NOV, LATER, log=lambda *a: None)
    names = dict(res.people.select("person_id", "name").rows())
    assert (names["Q216569"], names["Q313727"], names["Q181799"]) == ("Roy Scheider", "Robert Shaw", None)


def test_m3_snapshot_pruning_leaves_credits_alone(fake):
    cr.ingest(fake.fetcher(), FILMS, NOV, LATER, log=lambda *a: None)
    assert wd.prune_snapshots(set()) == 0
    assert len(cr.cached_entries()) == 4


def test_run_reads_the_matched_titles_and_writes_the_tables(fake):
    site = paths.site_data()
    site.mkdir(parents=True)
    pl.DataFrame({"title_id": ["tt0073195", "tt0114709", "bb_x"], "wikidata_qid": ["Q189505", "Q171048", None],
                  "title": ["Jaws", "Toy Story", "Unmatched"], "pre1982_baseline_gross": [None, None, None]},
                 schema_overrides={"pre1982_baseline_gross": pl.Int64}).write_parquet(site / "titles.parquet")
    pl.DataFrame({"release_id": ["a", "b", "c"], "title_id": ["tt0073195", "tt0114709", "bb_x"]}).write_parquet(
        site / "releases.parquet")
    pl.DataFrame({"release_id": ["a", "a", "b", "c"], "total_gross": [100, 260, 191, 5]}).write_parquet(
        site / "snapshots.parquet")
    assert [f.title_id for f in cr.matched_films(site)] == ["tt0073195", "tt0114709"]
    out = cr.run(fake.fetcher(), today=NOV, deadline=LATER)
    assert [p.name for p in out] == ["people.parquet", "credits.parquet"]
    assert pl.read_parquet(site / "credits.parquet").schema == pl.Schema(cr.CREDITS_SCHEMA)
    assert pl.read_parquet(site / "people.parquet").schema == pl.Schema(cr.PEOPLE_SCHEMA)
    report = json.loads((paths.data_build() / "credits_report.json").read_text())
    assert report["films"] == 2 and report["top_without_director"] == []
