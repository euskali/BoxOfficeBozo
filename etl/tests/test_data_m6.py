"""M6 golden tests: the ranking SQL (site/src/queries) on the real built tables.

PR CI has no data, so these skip there; the data-build job in deploy.yml sets BOFFO_REQUIRE_DATA=1
and runs them before every deploy. Each expected fact cites where it comes from (read Nov 2026):

- Star Wars is the domestic #1 when E.T. opens (11 Jun 1982) on its pre-1982 baseline: Box Office
  Mojo's release summary gives its 1977 release, every run before the 1982 re-issue, $307,263,857
  (data/manual/pre1982_baseline.csv). E.T. passed it during its first run, by 19 Jan 1983:
  StarWars.com's "Celebrating E.T." (posted 19 Jan 2013) says Variety ran George Lucas's full-page
  ad congratulating Spielberg on it thirty years earlier that day
  (https://www.starwars.com/news/celebrating-e-t).
- Titanic passed Star Wars' $461M domestic record on Saturday 14 Mar 1998: The Spokesman-Review,
  "The Really Big Show", 15 Mar 1998
  (https://www.spokesman.com/stories/1998/mar/15/the-really-big-show/). So it leads on the chart of
  the weekend ending 15 Mar 1998.
- Avatar reached $601.1M on Tuesday 2 Feb 2010, just past Titanic's $600.8M: Associated Press,
  Los Angeles, 3 Feb 2010 (https://6abc.com/archive/7249521/). First weekend chart after: 7 Feb.
- The Force Awakens passed Avatar's $760.5M late on Wednesday 6 Jan 2016, at an estimated $764.4M:
  BuzzFeed News, 7 Jan 2016
  (https://www.buzzfeednews.com/article/adambvary/the-force-awakens-avatar-box-office). First
  weekend chart after: 10 Jan.
- On admissions, Gone with the Wind is #1: Box Office Mojo's all-time chart in estimated tickets,
  Wayback capture of 22 Dec 2018, ranks it first with 202,044,600, ahead of Star Wars' 178,119,600
  (https://web.archive.org/web/20181222025445/https://www.boxofficemojo.com/alltime/adjusted.htm?adjust_yr=1&p=.htm;
  data/manual/admissions_estimates.csv). Its lead is the baseline's, so it holds from 1982 on.
"""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from boffo_etl import paths, queries
from test_data_m3 import _require

STAR_WARS, ET, GWTW = "tt0076759", "tt0083866", "tt0031381"
TITANIC, AVATAR, TFA = "tt0120338", "tt0499549", "tt2488496"
ESTIMATES = {GWTW: 202_044_600, STAR_WARS: 178_119_600}  # Box Office Mojo, 22 Dec 2018
ESTIMATED_ON = date(2018, 12, 22)


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    for name in queries.TABLES:
        path = _require(paths.site_data() / f"{name}.parquet").as_posix().replace("'", "''")
        c.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{path}')")
    yield c
    c.close()


def leader(con, day: date, measure: str = "nominal") -> str:
    return queries.leaderboard(con, day, measure, limit=1)[0]["title_id"]


def first_number_one(con, title_id: str, measure: str = "nominal") -> date:
    return min(r["as_of"] for r in queries.film_rank_timeline(con, title_id, measure) if r["rank"] == 1)


def test_star_wars_leads_until_et_passes_it_in_its_first_run(con):
    assert leader(con, date(1982, 1, 1)) == STAR_WARS
    assert leader(con, date(1982, 6, 6)) == STAR_WARS  # the weekend before E.T. opened
    passed = first_number_one(con, ET)
    assert date(1982, 6, 13) <= passed <= date(1983, 1, 19)
    before = [r for r in queries.film_rank_timeline(con, STAR_WARS, "nominal") if r["as_of"] < passed]
    assert {r["rank"] for r in before} == {1}


def test_titanic_becomes_number_one_on_the_weekend_of_14_march_1998(con):
    assert leader(con, date(1998, 3, 8)) == STAR_WARS
    assert first_number_one(con, TITANIC) == date(1998, 3, 15)


def test_avatar_passes_titanic_in_early_february_2010(con):
    assert leader(con, date(2010, 1, 31)) == TITANIC
    assert first_number_one(con, AVATAR) == date(2010, 2, 7)


def test_the_force_awakens_passes_avatar_in_january_2016(con):
    assert leader(con, date(2016, 1, 3)) == AVATAR
    assert first_number_one(con, TFA) == date(2016, 1, 10)


def test_gone_with_the_wind_leads_on_admissions_throughout(con):
    steps = queries.film_rank_timeline(con, GWTW, "admissions")
    assert steps[0]["as_of"] == date(1982, 1, 1)
    assert {r["rank"] for r in steps} == {1}
    assert leader(con, date(2026, 11, 22), "admissions") == GWTW


@pytest.mark.parametrize("title_id", list(ESTIMATES))
def test_a_baseline_films_admissions_match_the_published_estimate(con, title_id):
    """Its baseline admissions are the estimate less what the charts count by then (cume.py)."""
    [row] = queries.leaderboard(con, ESTIMATED_ON, "admissions", title_id=title_id)
    assert row["value"] == pytest.approx(ESTIMATES[title_id], abs=1)
    assert row["baseline"] is True and row["baseline_is_rental"] is False


@pytest.mark.parametrize("title_id", [STAR_WARS, ET, TITANIC])
@pytest.mark.parametrize("measure", queries.MEASURES)
def test_the_timeline_agrees_with_the_leaderboard(con, title_id, measure):
    steps = queries.film_rank_timeline(con, title_id, measure)
    for step in steps[:: max(1, len(steps) // 12)]:
        [row] = queries.leaderboard(con, step["as_of"], measure, title_id=title_id)
        assert (row["all_time_rank"], row["value"]) == (step["rank"], step["value"]), step["as_of"]
