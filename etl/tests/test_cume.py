"""M5: CPI dollars, admissions and title_cume, on small synthetic tables."""

from __future__ import annotations

import json
from datetime import date, timedelta

import polars as pl
import pytest

from boffo_etl import cume
from boffo_etl.fetch import FetchDisabledError

D = date


def snaps(rows: list[tuple]) -> pl.DataFrame:
    """(release_id, title_id, weekend_end, total_gross, weekend_gross, weeks)."""
    return pl.DataFrame(rows, schema={"release_id": pl.String, "title_id": pl.String, "weekend_end": pl.Date,
                                      "total_gross": pl.Int64, "weekend_gross": pl.Int64, "weeks": pl.Int32},
                        orient="row")


def titles(rows: list[tuple] = ()) -> pl.DataFrame:
    """(title_id, year, pre1982_baseline_gross, baseline_is_rental)."""
    return pl.DataFrame(list(rows), schema={"title_id": pl.String, "year": pl.Int32,
                                            "pre1982_baseline_gross": pl.Float64, "baseline_is_rental": pl.Boolean},
                        orient="row")


def releases(s: pl.DataFrame) -> pl.DataFrame:
    return s.select("release_id", pl.col("title_id").alias("title")).unique()


def cpi(values: dict[date, float]) -> pl.DataFrame:
    return pl.DataFrame({"month": list(values), "cpi": list(values.values())}, schema=cume.cpi_source.SCHEMA)


def tickets(prices: dict[int, float]) -> list[dict]:
    return [{"year": y, "avg_price_usd": p, "source": "Test source", "source_url": ""} for y, p in prices.items()]


def flat_cpi(first: date, last: date, v: float = 100.0) -> dict[date, float]:
    out, m = {}, first
    while m <= last:
        out[m] = v
        m = D(m.year + m.month // 12, m.month % 12 + 1, 1)
    return out


def built(s, t=None, c=None, p=None):
    t = titles() if t is None else t
    c = flat_cpi(D(1913, 1, 1), D(2026, 10, 1)) if c is None else c
    p = {y: 10.0 for y in range(1948, 2027)} if p is None else p
    return cume.build(s, releases(s), t, cpi(c), tickets(p))


def rows(b, title_id: str) -> list[tuple]:
    return b.cume.filter(pl.col("title_id") == title_id).select(
        "as_of", "cume_nominal", "cume_cpi", "cume_admissions").rows()


def test_delta_deflation_three_weekends_by_hand():
    """The M5 accept example. One release over three weekends that cross a month and a year:

    weekend      total      delta    CPI    ticket   delta in 1982-84 $          admissions
    1990-12-23   1,000,000  1,000,000  125.0  $4.00   1,000,000 x 100/125 = 800,000   250,000
    1990-12-30   1,800,000    800,000  125.0  $4.00     800,000 x 100/125 = 640,000   200,000
    1991-01-06   2,100,000    300,000  128.0  $5.00     300,000 x 100/128 = 234,375    60,000

    so cume_cpi = 800,000, 1,440,000, 1,674,375 and cume_admissions = 250,000, 450,000, 510,000.
    """
    s = snaps([("r1", "tt1", D(1990, 12, 23), 1_000_000, 1_000_000, 1),
               ("r1", "tt1", D(1990, 12, 30), 1_800_000, 800_000, 2),
               ("r1", "tt1", D(1991, 1, 6), 2_100_000, 300_000, 3)])
    b = built(s, c={D(1990, 12, 1): 125.0, D(1991, 1, 1): 128.0}, p={1990: 4.0, 1991: 5.0})
    assert rows(b, "tt1") == [(D(1990, 12, 23), 1_000_000, 800_000.0, 250_000.0),
                              (D(1990, 12, 30), 1_800_000, 1_440_000.0, 450_000.0),
                              (D(1991, 1, 6), 2_100_000, 1_674_375.0, 510_000.0)]
    assert b.cume["baseline"].to_list() == [False] * 3


def test_releases_of_a_title_add_up_and_unchanged_weekends_are_dropped():
    s = snaps([("orig", "tt1", D(1990, 6, 3), 100, 100, 1), ("orig", "tt1", D(1990, 6, 10), 150, 50, 2),
               ("orig", "tt1", D(1990, 6, 17), 150, 0, 3),  # no change
               ("rr", "tt1", D(1997, 6, 1), 30, 30, 1), ("rr", "tt1", D(1997, 6, 8), 40, 10, 2),
               ("other", "tt2", D(1990, 6, 10), 7, 7, 1)])
    b = built(s)
    assert [r[:2] for r in rows(b, "tt1")] == [(D(1990, 6, 3), 100), (D(1990, 6, 10), 150),
                                               (D(1997, 6, 1), 180), (D(1997, 6, 8), 190)]
    assert rows(b, "tt2") == [(D(1990, 6, 10), 7, 7.0, 0.7)]
    assert b.report["final_nominal"] == b.report["release_last_totals"] == 197


def test_a_total_that_goes_down_is_kept_as_charted():
    s = snaps([("r", "tt1", D(2023, 5, 21), 4_000, 4_000, 1), ("r", "tt1", D(2023, 5, 28), 28, 28, 2),
               ("r", "tt1", D(2023, 6, 4), 4_100, 72, 3)])
    b = built(s)
    assert [r[1] for r in rows(b, "tt1")] == [4_000, 28, 4_100]
    assert b.report["negative_deltas"] == 1


def test_a_late_run_counts_only_what_earlier_releases_dont_hold():
    """Box Office Mojo lists a late run under the original release with the lifetime total."""
    s = snaps([("first", "tt1", D(1985, 7, 7), 150, 150, 1), ("first", "tt1", D(1985, 7, 14), 200, 50, 2),
               # opened 1985-07-07 by its weeks counter; 230 to date, 5 of it this weekend
               ("late", "tt1", D(2024, 12, 29), 230, 5, 2061)])
    b = built(s)
    assert [r[:2] for r in rows(b, "tt1")] == [(D(1985, 7, 7), 150 + 25), (D(1985, 7, 14), 225), (D(2024, 12, 29), 230)]
    o = b.report["overlaps"][0]
    assert (o["release_id"], o["kind"], o["opened"], o["covered"], o["excess"]) == \
        ("late", "late_run", "1985-07-07", 200, 25)
    r = b.report
    assert r["final_nominal"] == r["release_last_totals"] + r["baseline_total"] - r["covered"] == 230


def test_a_late_run_alone_counts_its_whole_total_from_its_opening():
    s = snaps([("imax", "tt9", D(1999, 1, 3), 11_000, 40, 78)])
    opened = D(1999, 1, 3) - timedelta(weeks=77)
    b = built(s, c={**flat_cpi(D(1997, 1, 1), D(1999, 12, 1)), opened.replace(day=1): 50.0})
    assert rows(b, "tt9") == [(opened, 10_960, 21_920.0, 1_096.0), (D(1999, 1, 3), 11_000, 21_960.0, 1_100.0)]


def test_older_money_of_a_late_run_is_dated_1982_and_priced_at_its_opening():
    s = snaps([("jaws", "tt1", D(2024, 12, 29), 260_000, 700, 2585)])
    opened = D(2024, 12, 29) - timedelta(weeks=2584)
    assert opened.year == 1975
    b = built(s, c={**flat_cpi(D(1982, 1, 1), D(2026, 10, 1)), opened.replace(day=1): 50.0}, p={1975: 2.0, 2024: 10.0})
    assert rows(b, "tt1") == [(D(1982, 1, 1), 259_300, 518_600.0, 129_650.0),
                              (D(2024, 12, 29), 260_000, 519_300.0, 129_720.0)]


def test_a_baseline_is_priced_at_its_release_year():
    t = titles([("tt0076759", 1977, 1_000_000.0, False)])
    c = {**flat_cpi(D(1982, 1, 1), D(2026, 10, 1)), **{D(1977, m, 1): 60.0 + m for m in range(1, 13)}}  # 1977 avg 66.5
    b = built(snaps([]), t, c, {1977: 2.5, 1982: 3.0})
    assert rows(b, "tt0076759") == [(D(1982, 1, 1), 1_000_000, round(1_000_000 * 100 / 66.5, 2), 400_000.0)]
    assert b.cume["baseline"].to_list() == [True]
    assert b.report["baselines"] == 1 and b.report["baseline_total"] == 1_000_000


def test_a_baseline_titles_1982_carry_in_isnt_counted_twice():
    """A film still showing in January 1982: its 1981 earnings are in the baseline."""
    t = titles([("tt1", 1981, 400.0, False)])
    s = snaps([("raiders", "tt1", D(1982, 1, 3), 500, 20, 30), ("raiders", "tt1", D(1982, 1, 10), 515, 15, 31)])
    b = built(s, t)
    assert [r[:2] for r in rows(b, "tt1")] == [(D(1982, 1, 1), 400 + 80), (D(1982, 1, 3), 500), (D(1982, 1, 10), 515)]
    o = b.report["overlaps"][0]
    assert (o["kind"], o["covered"], o["excess"]) == ("carry_in", 400, 80)
    assert b.report["final_nominal"] == 515 and b.cume["baseline"].all()


def test_months_after_the_latest_cpi_use_the_latest_index():
    s = snaps([("r", "tt1", D(2026, 10, 4), 100, 100, 1), ("r", "tt1", D(2026, 11, 15), 300, 200, 2)])
    b = built(s, c={D(2026, 9, 1): 300.0, D(2026, 10, 1): 400.0})
    assert [r[2] for r in rows(b, "tt1")] == [25.0, 75.0]
    assert b.report["latest_cpi_month"] == "2026-10-01"
    assert (b.report["deltas_after_latest_cpi"], b.report["gross_after_latest_cpi"]) == (1, 200)


def test_a_year_with_no_ticket_price_leaves_admissions_null_from_then_on():
    t = titles([("tt0031381", 1939, 200.0, False)])
    b = built(snaps([("r", "tt0031381", D(1998, 3, 1), 50, 50, 1)]), t)
    assert [r[3] for r in rows(b, "tt0031381")] == [None, None]
    assert b.report["titles_without_admissions"] == 1


def test_ticket_prices_interpolate_gaps_and_carry_the_last_year_forward():
    t = cume.ticket_prices(tickets({1971: 1.65, 1974: 1.89, 1975: 2.03}), 2027)
    assert t["year"].to_list() == list(range(1971, 2028))
    assert t.filter(pl.col("year") == 1972).row(0) == (1972, pytest.approx(1.73), "interpolated between 1971 and 1974", True)
    assert t.filter(pl.col("year") == 1974).row(0) == (1974, 1.89, "Test source", False)
    assert t.filter(pl.col("year") == 2027).row(0) == (2027, 2.03, "carried forward from 1975", True)
    assert cume.ticket_prices([], 2026).height == 0


def test_the_real_ticket_price_csv_is_sourced_and_covers_1982_on(repo):
    from boffo_etl.manual import load_manual
    from conftest import REAL_REPO_ROOT

    rows_ = load_manual("ticket_prices.csv", REAL_REPO_ROOT / "data/manual")
    t = cume.ticket_prices(rows_, 2026)
    reported = set(t.filter(~pl.col("is_interpolated"))["year"].to_list())
    assert set(range(1974, 2020)) <= reported and 2022 in reported
    assert t.filter(pl.col("year") == 2021).row(0)[2] == "interpolated between 2019 and 2022"


def _site(repo, s: pl.DataFrame, t: pl.DataFrame):
    site = repo / "site/public/data"
    site.mkdir(parents=True)
    s.write_parquet(site / "snapshots.parquet")
    releases(s).write_parquet(site / "releases.parquet")
    t.write_parquet(site / "titles.parquet")
    return site


def test_run_writes_three_tables_and_a_report(repo):
    s = snaps([("r1", "tt1", D(1990, 12, 23), 1_000, 1_000, 1)])
    site = _site(repo, s, titles([("tt1", 1990, None, None)]))
    (repo / "data/build").mkdir(parents=True)
    cpi(flat_cpi(D(1990, 1, 1), D(1990, 12, 1))).write_parquet(repo / "data/build/cpi.parquet")
    (repo / "data/manual/ticket_prices.csv").write_text(
        "year,avg_price_usd,source,source_url,notes\n1990,4.22,NATO table,,\n", encoding="utf-8")
    out = cume.run(D(2026, 11, 22))
    assert [p.name for p in out] == ["cpi.parquet", "ticket_prices.parquet", "title_cume.parquet"]
    assert all(p.parent == site for p in out)
    tc = pl.read_parquet(site / "title_cume.parquet")
    assert tc.schema == pl.Schema(cume.CUME_SCHEMA) and tc.height == 1
    report = json.loads((repo / "data/build" / cume.REPORT).read_text())
    assert report["titles"] == 1 and report["built_on"] == "2026-11-22"


def test_run_needs_the_cpi_table(repo):
    _site(repo, snaps([("r1", "tt1", D(1990, 12, 23), 1_000, 1_000, 1)]), titles([("tt1", 1990, None, None)]))
    with pytest.raises(FetchDisabledError, match="cpi.parquet is missing"):
        cume.run()


def test_run_without_built_tables_does_nothing(repo):
    assert cume.run() == []
