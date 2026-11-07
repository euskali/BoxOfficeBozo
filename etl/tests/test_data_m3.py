"""M3 accept criteria, run against the real built tables.

PR CI has no data, so these skip there. The data-build job in deploy.yml sets
BOFFO_REQUIRE_DATA=1, which turns a missing table into a failure.

Accept: at least 97% of total nominal gross is matched to an IMDb id
(tconst), and all of the top 1,000 grossing releases are. Unmatched releases
keep a bb_ id and still appear on the site.

The spot checks' expected ids are the Wikidata items' own statements, read on
wikidata.org in November 2026: Titanic (Q44578) has P1237 "titanic" and P345
tt0120338; Avatar (Q24871) "avatar" and tt0499549; E.T. the Extra-Terrestrial
(Q11621) "et" and tt0083866; Star Wars: The Force Awakens (Q6074) "starwars7"
and tt2488496.
"""

from __future__ import annotations

import os

import duckdb
import pytest

from boffo_etl import paths


def _require(path):
    if path.is_file():
        return path
    if os.environ.get("BOFFO_REQUIRE_DATA") == "1":
        pytest.fail(f"{path} is missing and BOFFO_REQUIRE_DATA=1")
    pytest.skip(f"{path.name} not built (data is built in CI)")


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    for view, name in (("s", "snapshots"), ("r", "releases"), ("t", "titles")):
        path = _require(paths.site_data() / f"{name}.parquet")
        literal = "'" + str(path).replace("'", "''") + "'"
        c.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet({literal})")
    c.execute("""CREATE TEMP TABLE g AS
                 SELECT r.release_id, r.title, r.title_id, coalesce(max(s.total_gross), 0) AS gross
                 FROM r LEFT JOIN s USING (release_id) GROUP BY ALL""")
    yield c
    c.close()


def test_97_percent_of_gross_is_matched(con):
    share = con.execute("""SELECT sum(gross) FILTER (WHERE title_id LIKE 'tt%') / sum(gross) FROM g""").fetchone()[0]
    assert share >= 0.97


def test_top_1000_releases_are_matched(con):
    unmatched = con.execute("""
        SELECT release_id, title, gross FROM (SELECT * FROM g ORDER BY gross DESC, release_id LIMIT 1000)
        WHERE title_id NOT LIKE 'tt%' ORDER BY gross DESC""").fetchall()
    assert unmatched == []


def test_every_release_has_a_title(con):
    assert con.execute("SELECT count(*) FROM r ANTI JOIN t USING (title_id)").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM r WHERE match_method IS NULL").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM s JOIN r USING (release_id) "
                       "WHERE s.title_id IS DISTINCT FROM r.title_id").fetchone()[0] == 0


def test_imdb_titles_have_their_wikidata_item(con):
    assert con.execute("SELECT count(*) FROM t WHERE title_id LIKE 'tt%' AND wikidata_qid IS NULL").fetchone()[0] == 0


@pytest.mark.parametrize("legacy_id, title_id, qid", [
    ("titanic", "tt0120338", "Q44578"),
    ("avatar", "tt0499549", "Q24871"),
    ("et", "tt0083866", "Q11621"),
    ("starwars7", "tt2488496", "Q6074"),
])
def test_spot_checks(con, legacy_id, title_id, qid):
    row = con.execute("""SELECT r.title_id, t.wikidata_qid FROM r JOIN t USING (title_id)
                         WHERE r.release_id = 'legacy:' || ?""", [legacy_id]).fetchone()
    assert row == (title_id, qid)


@pytest.mark.parametrize("release_ids, title_id", [
    # 2012 3D (stat695), Box Office Mojo's "2017 Re-release" and "25 Year Anniversary" (archived pages)
    (("legacy:titanic3d", "bom:rl403015169", "bom:rl3167650561"), "tt0120338"),
    # 2010 Special Edition (stat695), "2022 Re-release"
    (("legacy:avatarspecialedition", "bom:rl2319418113"), "tt0499549"),
])
def test_rereleases_join_their_film(con, release_ids, title_id):
    rows = con.execute("SELECT release_id, title_id, is_rerelease FROM r WHERE list_contains(?, release_id)",
                       [list(release_ids)]).fetchall()
    assert sorted(rows) == sorted((rid, title_id, True) for rid in release_ids)
