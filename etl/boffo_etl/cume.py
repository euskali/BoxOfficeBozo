"""M5: inflation and admissions. Builds ``title_cume.parquet``, the table the time machine runs on.

One row per title per weekend where its total changed, with three cumulative measures:

- ``cume_nominal``: dollars as charted (plus a pre-1982 baseline when the title has one).
- ``cume_cpi``: constant dollars of CPI-U's own reference period, 1982-84 (index = 100). Each
  period delta is divided by the index of its weekend's month and multiplied by 100, so a value
  in dollars of any month M is ``cume_cpi * CPI(M) / 100``. The site rescales it that way to
  "today's dollars" or "dollars of the selected date".
- ``cume_admissions``: each delta divided by the average ticket price of its weekend's year.

Deltas: for each release, ``delta = total_gross - previous total_gross`` week by week; the first
delta is the first charted total. A total that goes down gives a negative delta, so
``cume_nominal`` is always the baseline plus each release's latest total, as charted
(``checks.py`` flags the drops; they aren't fixed here).

Late runs (M3): Box Office Mojo lists some films' later runs under the original release, with
the lifetime total (Shrek 2's run on the 2024-12-29 chart starts at $441.6M, its 2004 run
again). Such a release's total before its first chart here is money it earned earlier, and the
title's other releases (and baseline) may already hold it. So on the first weekend only that
weekend's gross counts, plus any of the earlier money that the title's other releases and baseline
don't account for (``excess``), dated to the run's opening (its weeks counter) or 1982-01-01 for
older films, and priced at that month. The same applies to a release a baseline title was
already showing in 1982 (a *carry-in*): its 1981 earnings are in the baseline.

Baselines (pre-1982 lifetime totals as of 1981-12-31, ``data/manual/pre1982_baseline.csv``)
get a row at 1982-01-01, priced at the release year's average CPI and ticket price (an
approximation; ``baseline`` is true on every row of such a title). Rentals stay rentals: the
title's ``baseline_is_rental`` says so.

That approximation fails for films whose pre-1982 money came from decades of re-issues.
Gone with the Wind's $189.5M spans 1939 to the 1970s: at 1939's CPI it would be $4.6B in October
2026 dollars, over twice what pricing by its estimated tickets gives, and there's no ticket price
before 1948 to count its admissions by. So a baseline film can have a published estimate of its lifetime
admissions as of some date (``data/manual/admissions_estimates.csv``). Its baseline admissions
are that estimate less what the title's charts here count up to that date, so the title's
lifetime admissions on that date equal the estimate. Its CPI dollars use the annual CPI of the
first year, from its release to 1981, whose average ticket price reaches the baseline's gross per
admission (the year its average ticket was sold, as it were). ``cume_report.json`` lists each.

A month BLS has no index for is interpolated in ``cpi.parquet`` (flagged ``is_interpolated``).
Months after the latest published CPI use the latest index, and years after the latest sourced
ticket price use that price; ``cume_report.json`` counts both, and the ticket price table flags
every year that isn't a sourced figure (``is_interpolated``).
"""

from __future__ import annotations

import bisect
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from . import match, paths
from .fetch import FetchDisabledError
from .manual import load_manual
from .sources import cpi as cpi_source

BASELINE_DATE = date(1982, 1, 1)
CPI_BASE = 100.0  # CPI-U's 1982-84 reference period
TICKET_SCHEMA = {"year": pl.Int32, "avg_price": pl.Float64, "source": pl.String, "is_interpolated": pl.Boolean}
CUME_SCHEMA = {"title_id": pl.String, "as_of": pl.Date, "cume_nominal": pl.Int64, "cume_cpi": pl.Float64,
               "cume_admissions": pl.Float64, "baseline": pl.Boolean}
DELTA_SCHEMA = {"title_id": pl.String, "release_id": pl.String, "as_of": pl.Date, "amount": pl.Int64,
                "priced_on": pl.Date, "kind": pl.String}
REPORT = "cume_report.json"
LISTED = 50

# Delta kinds: a weekend's change, a late run's (or carry-in's) earlier money no other release
# holds, and a pre-1982 baseline.
WEEKEND, BEFORE_CHART, BASELINE = "weekend", "before_chart", "baseline"


# --- ticket prices -----------------------------------------------------------------

def ticket_prices(rows: list[dict], through_year: int) -> pl.DataFrame:
    """Sourced years from ``ticket_prices.csv``; years between two sourced ones interpolated
    linearly, and years after the last one carried forward, both flagged ``is_interpolated``."""
    reported: dict[int, tuple[float, str]] = {}
    for r in rows:
        src = str(r["source"]) + (f" ({r['source_url']})" if r.get("source_url") else "")
        reported[int(r["year"])] = (float(r["avg_price_usd"]), src)
    if not reported:
        return pl.DataFrame(schema=TICKET_SCHEMA)
    years = sorted(reported)
    out = []
    for y in range(years[0], max(years[-1], through_year) + 1):
        if y in reported:
            out.append((y, reported[y][0], reported[y][1], False))
        elif y < years[-1]:
            i = bisect.bisect(years, y)
            y0, y1 = years[i - 1], years[i]
            p0, p1 = reported[y0][0], reported[y1][0]
            out.append((y, p0 + (p1 - p0) * (y - y0) / (y1 - y0), f"interpolated between {y0} and {y1}", True))
        else:
            out.append((y, reported[years[-1]][0], f"carried forward from {years[-1]}", True))
    return pl.DataFrame(out, schema=TICKET_SCHEMA, orient="row")


# --- deltas ------------------------------------------------------------------------

@dataclass
class Deltas:
    table: pl.DataFrame  # DELTA_SCHEMA
    overlaps: list[dict]  # late runs and carry-ins, with what was covered
    negative: int
    releases_without_totals: list[str]  # charted, but never with a total: no rows for them
    last_totals: int  # every release's latest total, summed
    baseline_total: int


def _baselines(titles: pl.DataFrame) -> dict[str, tuple[int, bool, int | None]]:
    """title_id -> (baseline gross, is_rental, release year)."""
    b = titles.filter(pl.col("pre1982_baseline_gross").is_not_null())
    return {t: (round(g), bool(r), y) for t, g, r, y in
            zip(b["title_id"], b["pre1982_baseline_gross"], b["baseline_is_rental"], b["year"])}


def deltas(snapshots: pl.DataFrame, titles: pl.DataFrame, late: dict[str, date] | None = None) -> Deltas:
    """Every period delta of every title (see the module docstring)."""
    late = match.late_runs(snapshots) if late is None else late
    base = _baselines(titles)
    s = (snapshots.select("release_id", "title_id", "weekend_end", "total_gross", "weekend_gross", "weeks")
         .sort("release_id", "weekend_end"))
    with_totals = s.filter(pl.col("total_gross").is_not_null())
    runs: dict[str, list[tuple]] = defaultdict(list)
    title_of: dict[str, str] = {}
    for rid, tid, w, t, g, wk in with_totals.iter_rows():
        runs[rid].append((w, int(t), g, wk))
        title_of[rid] = tid
    by_title: dict[str, list[str]] = defaultdict(list)
    for rid, tid in title_of.items():
        by_title[tid].append(rid)
    weekends = {rid: [r[0] for r in rows] for rid, rows in runs.items()}

    def total_before(rid: str, day: date) -> int:
        i = bisect.bisect_left(weekends[rid], day)
        return runs[rid][i - 1][1] if i else 0

    out: list[tuple] = []
    overlaps: list[dict] = []
    negative = 0
    for tid in sorted(set(by_title) | set(base)):
        rids = sorted(by_title.get(tid, []), key=lambda r: (runs[r][0][0], r))
        b = base.get(tid)
        for rid in rids:
            rows = runs[rid]
            w1, t1, g1, wk1 = rows[0]
            opened = late.get(rid) or (w1 - timedelta(weeks=wk1 - 1) if wk1 and wk1 >= 1 else w1)
            if rid in late or (b is not None and opened < BASELINE_DATE):
                pre = max(t1 - max(g1 or 0, 0), 0)
                prior = (b[0] if b else 0) + sum(total_before(o, w1) for o in rids if o != rid)
                covered = min(pre, prior)
                excess = pre - covered
                out.append((tid, rid, w1, t1 - pre, w1, WEEKEND))
                if excess:
                    out.append((tid, rid, max(opened, BASELINE_DATE), excess, opened, BEFORE_CHART))
                overlaps.append({"release_id": rid, "title_id": tid, "kind": "late_run" if rid in late else "carry_in",
                                 "opened": opened.isoformat(), "first_weekend": w1.isoformat(), "first_total": t1,
                                 "first_weekend_gross": g1, "covered": covered, "excess": excess})
            else:
                out.append((tid, rid, w1, t1, w1, WEEKEND))
            for (_, prev, _, _), (w, t, _, _) in zip(rows, rows[1:]):
                if t < prev:
                    negative += 1
                out.append((tid, rid, w, t - prev, w, WEEKEND))
        if b is not None:
            year = b[2] or BASELINE_DATE.year - 1
            out.append((tid, None, BASELINE_DATE, b[0], date(year, 1, 1), BASELINE))
    without = sorted(s.group_by("release_id").agg(pl.col("total_gross").is_not_null().any().alias("any"))
                     .filter(~pl.col("any"))["release_id"].to_list())
    return Deltas(pl.DataFrame(out, schema=DELTA_SCHEMA, orient="row"), overlaps, negative, without,
                  sum(rows[-1][1] for rows in runs.values()), sum(b[0] for b in base.values()))


# --- pricing -----------------------------------------------------------------------

@dataclass
class Priced:
    table: pl.DataFrame  # DELTA_SCHEMA + cpi_dollars, admissions, cpi_carried, price_estimated
    notes: dict


def price(d: pl.DataFrame, cpi: pl.DataFrame, prices: pl.DataFrame) -> Priced:
    """Each delta in 1982-84 dollars (its month's CPI; a baseline's: its year's average) and in
    admissions (its year's ticket price). Months after the latest CPI use the latest index."""
    monthly = dict(zip(cpi["month"].to_list(), cpi["cpi"].to_list()))
    filled = set(cpi.filter(pl.col("is_interpolated"))["month"].to_list())
    latest_month = max(monthly) if monthly else None
    annual = {y: sum(v) / len(v) for y, v in _by_year(monthly).items()}
    tickets = dict(zip(prices["year"].to_list(), prices["avg_price"].to_list()))
    estimated = set(prices.filter(pl.col("is_interpolated"))["year"].to_list())
    cpi_values, adm, carried, est, interp = [], [], [], [], []
    for amount, priced_on, kind in d.select("amount", "priced_on", "kind").iter_rows():
        if kind == BASELINE:
            c = annual.get(priced_on.year)
            late = False
        else:
            m = priced_on.replace(day=1)
            late = latest_month is not None and m > latest_month
            c = monthly[latest_month] if late else monthly.get(m)
        p = tickets.get(priced_on.year)
        cpi_values.append(amount * CPI_BASE / c if c else None)
        adm.append(amount / p if p else None)
        carried.append(late)
        est.append(priced_on.year in estimated)
        interp.append(kind != BASELINE and priced_on.replace(day=1) in filled)
    table = d.with_columns(pl.Series("cpi_dollars", cpi_values, dtype=pl.Float64),
                           pl.Series("admissions", adm, dtype=pl.Float64),
                           pl.Series("cpi_carried", carried, dtype=pl.Boolean),
                           pl.Series("price_estimated", est, dtype=pl.Boolean),
                           pl.Series("cpi_interpolated", interp, dtype=pl.Boolean))
    return Priced(table, {"latest_cpi_month": latest_month.isoformat() if latest_month else None})


def _by_year(monthly: dict[date, float]) -> dict[int, list[float]]:
    out: dict[int, list[float]] = defaultdict(list)
    for m, v in monthly.items():
        out[m.year].append(v)
    return out


def apply_estimates(priced: pl.DataFrame, estimates: list[dict], cpi: pl.DataFrame,
                    prices: pl.DataFrame) -> tuple[pl.DataFrame, list[dict]]:
    """Price each baseline that has a published lifetime admissions estimate (see the module
    docstring). Returns the table and one report entry per estimate; an entry with a
    ``problem`` was not applied, and its baseline keeps its release-year pricing."""
    monthly = dict(zip(cpi["month"].to_list(), cpi["cpi"].to_list()))
    annual = {y: sum(v) / len(v) for y, v in _by_year(monthly).items()}
    tickets = dict(zip(prices["year"].to_list(), prices["avg_price"].to_list()))
    adm = priced["admissions"].to_list()
    cpi_dollars = priced["cpi_dollars"].to_list()
    est = priced["price_estimated"].to_list()
    rows = priced.select("title_id", "as_of", "amount", "priced_on", "kind").to_dicts()
    by_title: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_title[r["title_id"]].append(i)
    report = []
    for e in sorted(estimates, key=lambda e: e["title_id"]):
        tid, published, on = e["title_id"], int(e["admissions"]), e["as_of"]
        entry = {"title_id": tid, "title": e.get("title"), "published": published, "as_of": on.isoformat()}
        report.append(entry)
        base = [i for i in by_title.get(tid, []) if rows[i]["kind"] == BASELINE]
        if not base:
            entry["problem"] = "the title has no pre-1982 baseline"
            continue
        charted = [i for i in by_title[tid] if rows[i]["kind"] != BASELINE and rows[i]["as_of"] <= on]
        if any(adm[i] is None for i in charted):
            entry["problem"] = "some of the title's charted gross has no admissions"
            continue
        ours = sum(adm[i] for i in charted)
        b = base[0]
        gross, released = rows[b]["amount"], rows[b]["priced_on"].year
        admissions = published - ours
        entry["charted_admissions"] = round(ours)
        if admissions <= 0:
            entry["problem"] = f"the charts already count {round(ours):,} admissions by {on}"
            continue
        per_ticket = gross / admissions
        years = [y for y in range(released, BASELINE_DATE.year) if y in tickets and y in annual]
        if not years:
            entry["problem"] = f"no ticket price or CPI for any year from {released} to {BASELINE_DATE.year - 1}"
            continue
        cpi_year = next((y for y in years if tickets[y] >= per_ticket), years[-1])
        adm[b] = float(admissions)
        cpi_dollars[b] = gross * CPI_BASE / annual[cpi_year]
        est[b] = False
        entry |= {"baseline_gross": gross, "baseline_admissions": round(admissions),
                  "gross_per_admission": round(per_ticket, 3), "cpi_year": cpi_year}
    table = priced.with_columns(pl.Series("admissions", adm, dtype=pl.Float64),
                                pl.Series("cpi_dollars", cpi_dollars, dtype=pl.Float64),
                                pl.Series("price_estimated", est, dtype=pl.Boolean))
    return table, report


# --- cumulating --------------------------------------------------------------------

def title_cume(priced: pl.DataFrame) -> pl.DataFrame:
    """Sum deltas per title and weekend, then cumulate. A measure that can't be priced (a year
    with no ticket price, a month before 1913) leaves that title's measure null from there on."""
    if priced.height == 0:
        return pl.DataFrame(schema=CUME_SCHEMA)

    def summed(col: str) -> pl.Expr:
        return pl.when(pl.col(col).null_count() > 0).then(None).otherwise(pl.col(col).sum()).alias(col)

    g = (priced.group_by("title_id", "as_of")
         .agg(pl.col("amount").sum(), summed("cpi_dollars"), summed("admissions"),
              (pl.col("amount") != 0).any().alias("changed"), (pl.col("kind") == BASELINE).any().alias("_b"))
         .sort("title_id", "as_of"))
    out = g.with_columns(
        pl.col("amount").cum_sum().over("title_id").alias("cume_nominal"),
        pl.when(pl.col("cpi_dollars").is_null().cum_sum().over("title_id") > 0).then(None)
          .otherwise(pl.col("cpi_dollars").fill_null(0).cum_sum().over("title_id")).round(2).alias("cume_cpi"),
        pl.when(pl.col("admissions").is_null().cum_sum().over("title_id") > 0).then(None)
          .otherwise(pl.col("admissions").fill_null(0).cum_sum().over("title_id")).round(1).alias("cume_admissions"),
        pl.col("_b").any().over("title_id").alias("baseline"),
        (pl.int_range(pl.len()).over("title_id") == 0).alias("_first"),
    )
    return out.filter(pl.col("changed") | pl.col("_first")).select(list(CUME_SCHEMA)).cast(CUME_SCHEMA)


# --- the build step ----------------------------------------------------------------

@dataclass
class Built:
    cpi: pl.DataFrame
    tickets: pl.DataFrame
    cume: pl.DataFrame
    report: dict


def build(snapshots: pl.DataFrame, releases: pl.DataFrame, titles: pl.DataFrame, cpi: pl.DataFrame,
          ticket_rows: list[dict], estimates: list[dict] | None = None) -> Built:
    d = deltas(snapshots, titles)
    through = max([y.year for y in d.table["priced_on"].to_list()] + [cpi["month"].max().year if cpi.height else 0])
    tickets = ticket_prices(ticket_rows, through)
    p = price(d.table, cpi, tickets)
    p.table, applied = apply_estimates(p.table, estimates or [], cpi, tickets)
    cume = title_cume(p.table)
    return Built(cpi, tickets, cume, _report(d, p, tickets, cume, releases, titles) | {"admissions_estimates": applied})


def _report(d: Deltas, p: Priced, tickets: pl.DataFrame, cume: pl.DataFrame, releases: pl.DataFrame,
            titles: pl.DataFrame) -> dict:
    t = p.table
    names = dict(zip(releases["release_id"].to_list(), releases["title"].to_list()))
    weekend = t.filter(pl.col("kind") != BASELINE)
    gross = int(weekend["amount"].sum() or 0)

    def share(mask: pl.Expr) -> float:
        return float(weekend.filter(mask)["amount"].sum() or 0) / gross if gross else 0.0

    overlaps = sorted(d.overlaps, key=lambda o: (-o["excess"], o["release_id"]))
    for o in overlaps:
        o["title"] = names.get(o["release_id"])
    final = cume.group_by("title_id").agg(pl.col("cume_nominal").sort_by("as_of").last())
    no_adm = cume.filter(pl.col("cume_admissions").is_null())["title_id"].unique().sort().to_list()
    no_cpi = cume.filter(pl.col("cume_cpi").is_null())["title_id"].unique().sort().to_list()
    reported = tickets.filter(~pl.col("is_interpolated"))["year"].to_list()
    carried_years = tickets.filter(pl.col("source").str.starts_with("carried forward"))["year"].to_list()
    interpolated = tickets.filter(pl.col("source").str.starts_with("interpolated"))["year"].to_list()
    base = titles.filter(pl.col("pre1982_baseline_gross").is_not_null())
    return {
        "cpi_base": cpi_source.BASE,
        "titles": cume["title_id"].n_unique(),
        "rows": cume.height,
        "deltas": t.height,
        "negative_deltas": d.negative,
        "releases_without_totals": len(d.releases_without_totals),
        "releases_without_totals_examples": [{"release_id": r, "title": names.get(r)}
                                             for r in d.releases_without_totals[:LISTED]],
        "latest_cpi_month": p.notes["latest_cpi_month"],
        "deltas_after_latest_cpi": int(t["cpi_carried"].sum()),
        "gross_after_latest_cpi": int(t.filter(pl.col("cpi_carried"))["amount"].sum() or 0),
        "deltas_at_interpolated_cpi": int(t["cpi_interpolated"].sum()),
        "gross_at_interpolated_cpi": int(t.filter(pl.col("cpi_interpolated"))["amount"].sum() or 0),
        "ticket_years": [min(tickets["year"]), max(tickets["year"])] if tickets.height else None,
        "ticket_years_reported": len(reported),
        "ticket_years_interpolated": interpolated,
        "ticket_years_carried_forward": carried_years,
        "gross_share_at_estimated_price": round(share(pl.col("price_estimated")), 4),
        "titles_without_admissions": len(no_adm),
        "titles_without_admissions_examples": no_adm[:LISTED],
        "titles_without_cpi": len(no_cpi),
        "titles_without_cpi_examples": no_cpi[:LISTED],
        "baselines": base.height,
        "baselines_rental": int(base["baseline_is_rental"].sum() or 0) if base.height else 0,
        "late_runs": sum(o["kind"] == "late_run" for o in overlaps),
        "carry_ins": sum(o["kind"] == "carry_in" for o in overlaps),
        "covered": int(sum(o["covered"] for o in overlaps)),
        "excess": int(sum(o["excess"] for o in overlaps)),
        "overlaps": overlaps[:LISTED],
        "final_nominal": int(final["cume_nominal"].sum() or 0),
        "release_last_totals": d.last_totals,
        "baseline_total": d.baseline_total,
    }


def run(today: date | None = None) -> list[Path]:
    """Build step, after matching: write cpi.parquet, ticket_prices.parquet and title_cume.parquet."""
    today = today or datetime.now(timezone.utc).date()
    site_dir, build_dir = paths.site_data(), paths.data_build()
    tables = {n: site_dir / f"{n}.parquet" for n in ("snapshots", "releases", "titles")}
    if not all(p.is_file() for p in tables.values()):
        print("  cume: snapshots, releases and titles aren't built, so there's nothing to cumulate")
        return []
    cpi_path = build_dir / "cpi.parquet"
    if not cpi_path.is_file():
        raise FetchDisabledError("data/build/cpi.parquet is missing (the cpi step fetches BLS CPI in CI)")
    built = build(pl.read_parquet(tables["snapshots"]), pl.read_parquet(tables["releases"]),
                  pl.read_parquet(tables["titles"]), pl.read_parquet(cpi_path),
                  load_manual("ticket_prices.csv", paths.data_manual()),
                  load_manual("admissions_estimates.csv", paths.data_manual()))
    out = [site_dir / "cpi.parquet", site_dir / "ticket_prices.parquet", site_dir / "title_cume.parquet"]
    built.cpi.write_parquet(out[0])
    built.tickets.write_parquet(out[1])
    built.cume.write_parquet(out[2])
    r = built.report | {"built_on": today.isoformat()}
    (build_dir / REPORT).write_text(json.dumps(r, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"  cume: {r['titles']} titles, {r['rows']} rows in {r['cpi_base']} dollars; CPI through "
          f"{r['latest_cpi_month']}; ticket prices {r['ticket_years']} ({r['ticket_years_reported']} sourced); "
          f"{r['late_runs']} late runs and {r['carry_ins']} carry-ins (${r['covered']:,} already counted, "
          f"${r['excess']:,} added); {r['titles_without_admissions']} titles without admissions")
    return out
