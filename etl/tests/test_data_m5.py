"""M5 accept criteria, run against the real built tables.

PR CI has no data, so these skip there. The data-build job in deploy.yml sets
BOFFO_REQUIRE_DATA=1, which turns a missing table into a failure.

Accept: admissions for a known film are within ±5% of a published estimate.

The published estimates are Box Office Mojo's, from its "All Time Box Office
Adjusted for Ticket Price Inflation" chart as archived by the Wayback Machine on
14 June 2018 (https://web.archive.org/web/20180614130433/http://www.boxofficemojo.com/alltime/adjusted.htm).
Its footnote says the chart is "adjusted to the estimated 2018 average ticket
price of $9.16" and that the adjustment "is mostly done by multiplying
estimated admissions by the latest average ticket price", so its admissions
estimate is the adjusted gross divided by $9.16. The same rows give each film's
unadjusted (nominal) gross at the time:

  film                                     adjusted gross   / $9.16 = admissions   unadjusted gross
  Titanic (tt0120338)                      $1,241,636,300            135.55M        $659,363,944
  Avatar (tt0499549)                         $891,355,700             97.31M        $760,507,625
  Star Wars: The Force Awakens (tt2488496)   $990,334,300            108.12M        $936,662,225

They're compared with our totals as of 2018-06-10, the last weekend before the
capture. E.T. (#4 there) isn't used: the 1982-83 weekly charts in stat695data
stop before its run ended ($419.5M of its $435.1M), so our total, and its
admissions, run about 4-6% low.

CPI facts are BLS's own (series CUUR0000SA0, https://data.bls.gov/timeseries/CUUR0000SA0):
the index is 9.8 in January 1913 and averages 100 over 1982-84 (its reference
period), and the October 2026 index was 337.511 (read from the BLS Public Data
API on 22 Nov 2026). Ticket prices are the sourced rows of
data/manual/ticket_prices.csv (NATO's table: $4.69 in 1998).
"""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from boffo_etl import paths
from test_data_m3 import _require

AS_OF = date(2018, 6, 10)
PRICE_2018 = 9.16
PUBLISHED = {  # title_id: (adjusted gross, unadjusted gross), Box Office Mojo, 14 Jun 2018
    "tt0120338": (1_241_636_300, 659_363_944),  # Titanic
    "tt0499549": (891_355_700, 760_507_625),  # Avatar
    "tt2488496": (990_334_300, 936_662_225),  # Star Wars: The Force Awakens
}
SHREK_2, SHREK_2_2018 = "tt0298148", 441_226_247  # its unadjusted gross on the same chart


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    for view, name in (("cume", "title_cume"), ("cpi", "cpi"), ("tp", "ticket_prices"), ("s", "snapshots")):
        path = _require(paths.site_data() / f"{name}.parquet")
        literal = "'" + str(path).replace("'", "''") + "'"
        c.execute(f"CREATE VIEW {view} AS SELECT * FROM read_parquet({literal})")
    yield c
    c.close()


def _as_of(con, title_id: str, day: date) -> tuple:
    return con.execute("""SELECT cume_nominal, cume_cpi, cume_admissions FROM cume
                          WHERE title_id = ? AND as_of <= ? ORDER BY as_of DESC LIMIT 1""", [title_id, day]).fetchone()


@pytest.mark.parametrize("title_id", list(PUBLISHED))
def test_admissions_are_within_5_percent_of_the_published_estimate(con, title_id):
    adjusted, _ = PUBLISHED[title_id]
    _, _, admissions = _as_of(con, title_id, AS_OF)
    assert admissions == pytest.approx(adjusted / PRICE_2018, rel=0.05)


@pytest.mark.parametrize("title_id", list(PUBLISHED))
def test_nominal_totals_match_the_same_chart(con, title_id):
    _, unadjusted = PUBLISHED[title_id]
    nominal, _, _ = _as_of(con, title_id, AS_OF)
    assert nominal == pytest.approx(unadjusted, rel=0.01)


def test_a_late_run_listing_isnt_counted_twice(con):
    """Shrek 2 is on the 2024-12-29 chart under its 2004 release with its lifetime total. Since 2018
    it has added only a small 2024 re-release; counting that listing in full would nearly double it."""
    nominal = con.execute("SELECT arg_max(cume_nominal, as_of) FROM cume WHERE title_id = ?", [SHREK_2]).fetchone()[0]
    assert SHREK_2_2018 <= nominal < 1.05 * SHREK_2_2018


def test_cpi_matches_bls(con):
    def cpi(month: date) -> float:
        return con.execute("SELECT cpi FROM cpi WHERE month = ?", [month]).fetchone()[0]

    assert cpi(date(1913, 1, 1)) == 9.8
    assert cpi(date(2026, 10, 1)) == 337.511
    base = con.execute("SELECT avg(cpi) FROM cpi WHERE month BETWEEN '1982-01-01' AND '1984-12-01'").fetchone()[0]
    assert base == pytest.approx(100.0, abs=0.05)


def test_ticket_prices_keep_sourced_years_and_flag_the_rest(con):
    assert con.execute("SELECT avg_price, is_interpolated FROM tp WHERE year = 1998").fetchone() == (4.69, False)
    assert con.execute("SELECT is_interpolated FROM tp WHERE year = 2021").fetchone() == (True,)


def test_every_title_with_a_total_has_all_three_measures(con):
    assert con.execute("""SELECT count(DISTINCT title_id) FROM s WHERE total_gross IS NOT NULL
                          AND title_id NOT IN (SELECT title_id FROM cume)""").fetchone()[0] == 0
    # Every charted gross is from 1982 on, after the first sourced ticket price (1948).
    assert con.execute("SELECT count(*) FROM cume WHERE cume_cpi IS NULL OR cume_admissions IS NULL").fetchone()[0] == 0
