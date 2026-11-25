"""M4 accept criteria, run against the real built tables.

PR CI has no data, so these skip there. The CI data build (build-data.yml) sets
BOFFO_REQUIRE_DATA=1, which turns a missing table into a failure.

Accept: Spielberg's titles include Jaws, E.T. and Jurassic Park. Tom Hanks has
Toy Story and Forrest Gump, within his top 4 billed.

The expected facts are the Wikidata items' own statements, read through the
Wikidata API (wbgetentities) and QLever in November 2026:
- Steven Spielberg (Q8877, P345 nm0000229) is the director (P57) of Jaws
  (Q189505, P345 tt0073195), E.T. the Extra-Terrestrial (Q11621, tt0083866)
  and Jurassic Park (Q167726, tt0107290).
- Tom Hanks (Q2263, P345 nm0000158) is the first voice actor (P725) statement
  of Toy Story (Q171048, tt0114709), which has no cast member (P161)
  statements, and the first cast member (P161) statement of Forrest Gump
  (Q134773, tt0109830).
"""

from __future__ import annotations

import duckdb
import pytest

from boffo_etl import paths
from test_data_m3 import _require

SPIELBERG, HANKS = "Q8877", "Q2263"


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    for view, name in (("c", "credits"), ("p", "people"), ("t", "titles")):
        path = _require(paths.site_data() / f"{name}.parquet")
        literal = "'" + str(path).replace("'", "''") + "'"
        c.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet({literal})")
    yield c
    c.close()


def test_people_are_identified(con):
    assert con.execute("SELECT person_id, imdb_id, name FROM p WHERE person_id IN (?, ?) ORDER BY 1",
                       [HANKS, SPIELBERG]).fetchall() == [(HANKS, "nm0000158", "Tom Hanks"),
                                                          (SPIELBERG, "nm0000229", "Steven Spielberg")]


def test_spielberg_directed_jaws_et_and_jurassic_park(con):
    films = {r[0] for r in con.execute("SELECT title_id FROM c WHERE person_id = ? AND role = 'director'",
                                       [SPIELBERG]).fetchall()}
    assert {"tt0073195", "tt0083866", "tt0107290"} <= films


@pytest.mark.parametrize("title_id", ["tt0114709", "tt0109830"])  # Toy Story (voice), Forrest Gump
def test_hanks_is_top_4_billed(con, title_id):
    billing = con.execute("SELECT billing FROM c WHERE person_id = ? AND role = 'actor' AND title_id = ?",
                          [HANKS, title_id]).fetchone()
    assert billing is not None and billing[0] <= 4


def test_credits_join_titles_and_people(con):
    assert con.execute("SELECT count(*) FROM c ANTI JOIN t USING (title_id)").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM c ANTI JOIN p USING (person_id)").fetchone()[0] == 0
    # The biggest films are fetched first, so even a run cut short by its time budget has these.
    assert con.execute("SELECT count(DISTINCT title_id) FROM c").fetchone()[0] > 1_000
