"""M6/M7: the site's SQL (site/src/queries/*.sql), executed here with duckdb on the shared
synthetic fixture (site/src/queries/testdata/fixture.sql). queries.test.ts runs the same files on
the same fixture in DuckDB-WASM. Expected values are worked out by hand in the fixture's header."""

from __future__ import annotations

import json
from datetime import date

import duckdb
import pytest

from boffo_etl import queries
from conftest import REAL_REPO_ROOT

QUERIES = REAL_REPO_ROOT / "site" / "src" / "queries"
NAMES = ("leaderboard", "film_rank_timeline", "person_totals", "weekend_chart", "cpi_factor",
         "latest_date", "film", "film_credits", "film_releases", "film_weekends", "person",
         "filmography", "browse_films", "search_index", "search")
ALL = ("test_alpha", "test_bravo", "test_charlie", "test_delta", "test_echo", "test_foxtrot")


@pytest.fixture()
def con():
    c = duckdb.connect()
    c.execute((QUERIES / "testdata" / "fixture.sql").read_text(encoding="utf-8"))
    yield c
    c.close()


def ranks(rows: list[dict]) -> list[tuple]:
    return [(r["title_id"], r["rank"]) for r in rows]


def test_every_query_file_is_wrapped():
    assert sorted(p.stem for p in QUERIES.glob("*.sql")) == sorted(NAMES)
    assert queries.SQL_DIR == QUERIES


def test_python_duckdb_is_the_engine_duckdb_wasm_bundles():
    pinned = json.loads((QUERIES / "engine.json").read_text(encoding="utf-8"))
    package = json.loads((REAL_REPO_ROOT / "site" / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["@duckdb/duckdb-wasm"] == pinned["duckdb-wasm"]
    assert duckdb.connect().execute("SELECT version()").fetchone()[0] == pinned["engine"]


# --- leaderboard ---------------------------------------------------------------------

def test_leaderboard_ranks_each_titles_latest_total(con):
    assert ranks(queries.leaderboard(con, "1991-01-10", "nominal")) == [
        ("test_alpha", 1), ("test_echo", 2), ("test_bravo", 3), ("test_charlie", 4)]
    rows = queries.leaderboard(con, date(1995, 6, 4), "nominal")
    assert ranks(rows) == [("test_delta", 1), ("test_bravo", 2), ("test_alpha", 3),
                           ("test_charlie", 3), ("test_echo", 5), ("test_foxtrot", 6)]
    assert [r["value"] for r in rows] == [1000, 400, 300, 300, 250, 120]
    assert {r["matching"] for r in rows} == {6}


def test_leaderboard_on_a_date_uses_the_latest_row_on_or_before_it(con):
    rows = queries.leaderboard(con, "1991-01-13", "nominal")
    assert ranks(rows) == [("test_bravo", 1), ("test_alpha", 2), ("test_charlie", 2), ("test_echo", 4)]
    assert rows[0]["last_change"] == date(1991, 1, 13)
    assert queries.leaderboard(con, "1981-12-31", "nominal") == []
    assert ranks(queries.leaderboard(con, "1982-01-01", "nominal")) == [("test_echo", 1)]


def test_leaderboard_measures(con):
    assert [r["title_id"] for r in queries.leaderboard(con, "1995-06-04", "cpi")] == [
        "test_delta", "test_echo", "test_alpha", "test_bravo", "test_charlie"]  # foxtrot's latest row is unpriced
    assert [r["value"] for r in queries.leaderboard(con, "1993-01-03", "cpi", title_id="test_foxtrot")] == [90.0]
    assert queries.leaderboard(con, "1993-01-10", "cpi", title_id="test_foxtrot") == []
    rows = queries.leaderboard(con, "1995-06-04", "admissions")
    assert [(r["title_id"], r["value"]) for r in rows] == [
        ("test_delta", 250.0), ("test_echo", 200.0), ("test_bravo", 160.0), ("test_alpha", 150.0),
        ("test_charlie", 120.0)]
    echo = rows[1]
    assert (echo["baseline"], echo["baseline_is_rental"]) == (True, True)
    with pytest.raises(duckdb.Error, match="unknown measure"):
        queries.leaderboard(con, "1995-06-04", "gross")


def test_leaderboard_filters_keep_all_time_ranks(con):
    rows = queries.leaderboard(con, "1995-06-04", "nominal", from_year=1991)
    assert [(r["title_id"], r["rank"], r["all_time_rank"]) for r in rows] == [
        ("test_delta", 1, 1), ("test_bravo", 2, 2), ("test_charlie", 3, 3), ("test_foxtrot", 4, 6)]
    assert [r["title_id"] for r in queries.leaderboard(con, "1995-06-04", "nominal", to_year=1990)] == [
        "test_alpha", "test_echo"]
    one = queries.leaderboard(con, "1991-01-13", "nominal", title_id="test_charlie")
    assert [(r["rank"], r["all_time_rank"], r["matching"]) for r in one] == [(1, 2, 1)]


def test_leaderboard_compares_with_an_earlier_date(con):
    rows = queries.leaderboard(con, "1995-06-04", "nominal", compare_to="1991-01-13")
    assert [(r["title_id"], r["rank"], r["prev_rank"]) for r in rows] == [
        ("test_delta", 1, None), ("test_bravo", 2, 1), ("test_alpha", 3, 2), ("test_charlie", 3, 2),
        ("test_echo", 5, 4), ("test_foxtrot", 6, None)]
    # prev_rank ranks within the year filters, as rank does
    rows = queries.leaderboard(con, "1995-06-04", "nominal", from_year=1991, compare_to="1991-01-13")
    assert [(r["title_id"], r["rank"], r["prev_rank"]) for r in rows] == [
        ("test_delta", 1, None), ("test_bravo", 2, 1), ("test_charlie", 3, 2), ("test_foxtrot", 4, None)]
    assert {r["prev_rank"] for r in queries.leaderboard(con, "1995-06-04", "nominal")} == {None}
    assert queries.latest_date(con) == date(1995, 6, 4)


def test_leaderboard_pages(con):
    page = queries.leaderboard(con, "1995-06-04", "nominal", limit=2, offset=2)
    assert ranks(page) == [("test_alpha", 3), ("test_charlie", 3)]
    assert page[0]["matching"] == 6


# --- film_rank_timeline ----------------------------------------------------------------

def test_timeline_steps_where_rank_or_value_changes(con):
    rows = queries.film_rank_timeline(con, "test_alpha", "nominal")
    assert [(r["as_of"], r["rank"], r["value"]) for r in rows] == [
        (date(1990, 1, 7), 2, 100), (date(1990, 1, 14), 1, 300),
        (date(1991, 1, 13), 2, 300), (date(1995, 6, 4), 3, 300)]
    rows = queries.film_rank_timeline(con, "test_charlie", "nominal")
    assert [(r["as_of"], r["rank"]) for r in rows] == [
        (date(1991, 1, 6), 4), (date(1991, 1, 13), 2), (date(1995, 6, 4), 3)]
    rows = queries.film_rank_timeline(con, "test_echo", "admissions")
    assert [(r["as_of"], r["rank"], r["value"]) for r in rows] == [
        (date(1982, 1, 1), 1, 200), (date(1995, 6, 4), 2, 200)]
    rows = queries.film_rank_timeline(con, "test_foxtrot", "cpi")
    assert [(r["as_of"], r["rank"], r["value"]) for r in rows] == [(date(1993, 1, 3), 5, 90), (date(1993, 1, 10), None, None)]
    rows = queries.film_rank_timeline(con, "test_foxtrot", "nominal")
    assert [(r["as_of"], r["rank"], r["value"]) for r in rows] == [
        (date(1993, 1, 3), 5, 80), (date(1993, 1, 10), 5, 120), (date(1995, 6, 4), 6, 120)]
    assert queries.film_rank_timeline(con, "no_such_title", "nominal") == []


@pytest.mark.parametrize("measure", queries.MEASURES)
@pytest.mark.parametrize("title_id", ALL)
def test_timeline_agrees_with_the_leaderboard_on_every_date(con, title_id, measure):
    steps = queries.film_rank_timeline(con, title_id, measure)
    days = [r[0] for r in con.execute("SELECT DISTINCT as_of FROM title_cume ORDER BY 1").fetchall()]
    for day in days:
        board = queries.leaderboard(con, day, measure, title_id=title_id)
        step = [s for s in steps if s["as_of"] <= day]
        if not board:
            assert not step or step[-1]["rank"] is None, day
            continue
        assert step[-1]["rank"] == board[0]["all_time_rank"], day
        assert step[-1]["value"] == board[0]["value"], day


# --- person_totals / person_rank ---------------------------------------------------------

def test_director_totals_count_every_credited_director(con):
    rows = queries.person_totals(con, "1995-06-04", "director", "nominal")
    assert [(r["person_id"], r["rank"], r["value"], r["titles"]) for r in rows] == [
        ("P1", 1, 1600, 3), ("P2", 2, 1400, 2), ("P3", 3, 250, 1)]
    assert rows[0]["name"] == "Test Director One"
    rows = queries.person_totals(con, "1991-01-10", "director", "nominal")
    assert [(r["person_id"], r["value"]) for r in rows] == [("P1", 350), ("P3", 250), ("P2", 200)]


def test_actor_totals_count_only_the_top_billed(con):
    rows = queries.person_totals(con, "1995-06-04", "actor", "nominal")
    assert [(r["person_id"], r["value"], r["titles"]) for r in rows] == [
        ("P10", 1300, 2), ("P11", 700, 2), ("P12", 550, 2)]  # P10's 5th billing and P13's unbilled credit don't count
    wider = queries.person_totals(con, "1995-06-04", "actor", "nominal", top_billed=5)
    assert wider[0]["person_id"] == "P10" and wider[0]["value"] == 1700


def test_person_rank_is_their_row_among_all_peers(con):
    r = queries.person_rank(con, "P12", "1995-06-04", "actor", "nominal")
    assert (r["rank"], r["value"], r["titles"], r["peers"]) == (3, 550, 2, 3)
    assert queries.person_rank(con, "P12", "1982-06-01", "actor", "admissions")["rank"] == 1
    assert queries.person_rank(con, "P10", "1982-06-01", "actor", "nominal") is None
    with pytest.raises(duckdb.Error, match="unknown role"):
        queries.person_totals(con, "1995-06-04", "writer", "nominal")


# --- weekend_chart / cpi_factor ------------------------------------------------------------

def test_weekend_chart_snaps_back_and_shows_last_weeks_rank(con):
    rows = queries.weekend_chart(con, "1991-01-16")
    assert [(r["weekend_end"], r["title_id"], r["rank"], r["last_rank"]) for r in rows] == [
        (date(1991, 1, 13), "test_charlie", 1, 2), (date(1991, 1, 13), "test_bravo", 2, 1)]
    first = queries.weekend_chart(con, "1991-01-06")
    assert [(r["title_id"], r["last_rank"]) for r in first] == [("test_bravo", None), ("test_charlie", None)]
    delta = queries.weekend_chart(con, "1995-06-04")[0]
    assert (delta["title"], delta["charted_title"], delta["label"], delta["is_estimate"]) == (
        "Test Film Delta", "Test Film Delta (Special Edition)", "Special Edition", True)
    assert queries.weekend_chart(con, "1989-12-31") == []


def test_weekend_chart_gives_last_weeks_gross_and_the_charts_either_side(con):
    rows = queries.weekend_chart(con, "1991-01-16")
    assert [(r["title_id"], r["weekend_gross"], r["last_weekend_gross"]) for r in rows] == [
        ("test_charlie", 250, 50), ("test_bravo", 200, 200)]
    assert {(r["prev_weekend_end"], r["next_weekend_end"]) for r in rows} == {(date(1991, 1, 6), date(1995, 6, 4))}
    delta = queries.weekend_chart(con, "1995-06-04")[0]  # the previous chart is years earlier
    assert (delta["last_rank"], delta["last_weekend_gross"], delta["prev_weekend_end"], delta["next_weekend_end"]) == (
        None, None, date(1991, 1, 13), None)
    assert queries.weekend_chart(con, "1990-01-07")[0]["prev_weekend_end"] is None


def test_cpi_factor_converts_1982_84_dollars(con):
    assert queries.cpi_factor(con, "1991-03-10") == {"month": date(1991, 1, 1), "factor": pytest.approx(1.346),
                                                     "is_interpolated": False}
    later = queries.cpi_factor(con, "2000-01-01")
    assert (later["month"], later["is_interpolated"]) == (date(1995, 6, 1), True)
    assert queries.cpi_factor(con, "1980-01-01") is None


# --- M7: film, person, browse and search pages ------------------------------------------------

def test_film_gives_the_titles_row_and_latest_totals(con):
    alpha = queries.film(con, "test_alpha")
    keys = ("title", "year", "release_date", "distributor", "genres", "mpaa", "first_as_of", "last_as_of",
            "cume_nominal", "cume_cpi", "cume_admissions", "baseline", "releases", "weekends",
            "first_weekend", "last_weekend")
    assert {k: alpha[k] for k in keys} == {
        "title": "Test Film Alpha", "year": 1990, "release_date": date(1990, 1, 5),
        "distributor": "Fictional Pictures", "genres": "Comedy", "mpaa": "PG",
        "first_as_of": date(1990, 1, 7), "last_as_of": date(1990, 1, 14), "cume_nominal": 300,
        "cume_cpi": 450, "cume_admissions": 150, "baseline": False, "releases": 1, "weekends": 2,
        "first_weekend": date(1990, 1, 7), "last_weekend": date(1990, 1, 14)}
    foxtrot = queries.film(con, "test_foxtrot")  # its latest row is unpriced: no CPI or admissions
    assert (foxtrot["cume_nominal"], foxtrot["cume_cpi"], foxtrot["cume_admissions"], foxtrot["releases"]) == (
        120, None, None, None)
    echo = queries.film(con, "test_echo")
    assert (echo["baseline"], echo["baseline_is_rental"], echo["pre1982_baseline_gross"]) == (True, True, 250)
    golf = queries.film(con, "test_golf")  # never charted
    assert (golf["title"], golf["cume_nominal"], golf["first_as_of"]) == ("The Golf Picture", None, None)
    assert queries.film(con, "no_such_title") is None


def test_film_credits_list_directors_then_cast_in_billing_order(con):
    assert [(r["role"], r["billing"], r["person_id"], r["name"]) for r in queries.film_credits(con, "test_delta")] == [
        ("director", None, "P1", "Test Director One"), ("director", None, "P2", "Test Director Two"),
        ("actor", 4, "P10", "Test Actor Ten")]
    assert [(r["role"], r["billing"], r["person_id"]) for r in queries.film_credits(con, "test_charlie")] == [
        ("director", None, "P1"), ("actor", 3, "P12"), ("actor", None, "P13")]


def test_film_releases_and_weekends(con):
    assert [(r["release_id"], r["label"], r["weekends"], r["is_rerelease"], r["total_gross"])
            for r in queries.film_releases(con, "test_delta")] == [("rel_delta", "Special Edition", 1, True, 1000)]
    assert [(r["weekend_end"], r["rank"], r["weekend_gross"], r["last_weekend_gross"], r["total_gross"])
            for r in queries.film_weekends(con, "test_bravo")] == [
        (date(1991, 1, 6), 1, 200, None, 200), (date(1991, 1, 13), 2, 200, 200, 400)]
    delta = queries.film_weekends(con, "test_delta")
    assert [(r["label"], r["is_estimate"], r["source"]) for r in delta] == [("Special Edition", True, "wayback")]
    assert queries.film_weekends(con, "test_echo") == []


def test_person_counts_credits_by_role(con):
    assert queries.person(con, "P1") == {"person_id": "P1", "name": "Test Director One", "imdb_id": None,
                                         "directed": 3, "acted": 0}
    p10 = queries.person(con, "P10")
    assert (p10["directed"], p10["acted"]) == (0, 3)
    assert queries.person(con, "P99") is None


def test_filmography_values_each_film_on_the_date(con):
    rows = queries.filmography(con, "P10", "1995-06-04", "nominal")
    assert [(r["title_id"], r["role"], r["billing"], r["counted"], r["value"], r["all_time_rank"]) for r in rows] == [
        ("test_alpha", "actor", 1, True, 300, 3), ("test_bravo", "actor", 5, False, 400, 2),
        ("test_delta", "actor", 4, True, 1000, 1)]
    early = queries.filmography(con, "P10", "1990-12-31", "nominal")
    assert [(r["title_id"], r["value"], r["all_time_rank"]) for r in early] == [
        ("test_alpha", 300, 1), ("test_bravo", None, None), ("test_delta", None, None)]
    cpi = queries.filmography(con, "P12", "1995-06-04", "cpi")
    assert [(r["title_id"], r["counted"], r["value"], r["all_time_rank"], r["baseline"], r["baseline_is_rental"])
            for r in cpi] == [("test_echo", True, 600, 2, True, True), ("test_charlie", True, 270, 5, False, None)]
    # counted follows person_totals: P10's counted films sum to its career total
    total = queries.person_rank(con, "P10", "1995-06-04", "actor", "nominal")["value"]
    assert sum(r["value"] for r in rows if r["counted"]) == total


def test_browse_files_films_by_first_letter_past_a_leading_article(con):
    rows = queries.browse_films(con, "T")
    assert [(r["title_id"], r["gross"]) for r in rows] == [
        ("test_alpha", 300), ("test_bravo", 400), ("test_charlie", 300), ("test_delta", 1000),
        ("test_echo", 250), ("test_foxtrot", 120)]
    assert {r["matching"] for r in rows} == {6}
    assert [r["title_id"] for r in queries.browse_films(con, "T", limit=2, offset=1)] == ["test_bravo", "test_charlie"]
    assert [(r["title"], r["gross"]) for r in queries.browse_films(con, "g")] == [("The Golf Picture", None)]
    assert [r["title_id"] for r in queries.browse_films(con, "#")] == ["test_hotel"]
    assert queries.browse_films(con, "Z") == []


def test_search_finds_films_and_people_by_word_start(con):
    queries.build_search_index(con)

    def hits(text, limit=8):
        return [(r["kind"], r["id"], r["match"]) for r in queries.search(con, text, limit)]

    assert hits("alpha") == [("film", "test_alpha", 2)]
    assert hits("golf picture") == [("film", "test_golf", 0)]  # "The" aside
    assert hits("9 hotel") == [("film", "test_hotel", 1)]
    # films by gross, then people by credits (ties by name)
    assert hits("test", 3) == [("film", "test_delta", 1), ("film", "test_bravo", 1), ("film", "test_alpha", 1),
                               ("person", "P10", 1), ("person", "P1", 1), ("person", "P11", 1)]
    assert hits("Test-Film  ALPHA!") == [("film", "test_alpha", 0)]  # punctuation and case aside
    assert hits("testdirector") == [("person", "P1", 3), ("person", "P2", 3), ("person", "P3", 3)]
    assert hits("...") == []
    assert hits("zzz") == []
    row = queries.search(con, "ten")[0]
    assert (row["name"], row["directed"], row["acted"], row["weight"]) == ("Test Actor Ten", 0, 3, 3)
