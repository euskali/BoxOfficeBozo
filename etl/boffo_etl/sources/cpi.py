"""M5: CPI-U monthly, U.S. city average, all items, not seasonally adjusted.

Source: U.S. Bureau of Labor Statistics series CUUR0000SA0 (1913 onward),
public domain; cite BLS. Fetched straight from the BLS Public Data API v1
(api.bls.gov) through ``boffo_etl.fetch``, in CI only, and written to
``data/build/cpi.parquet`` (``cume.py`` publishes it with the site tables).

The v1 API needs no key. It answers up to 10 years per request, and only as a
POST (a GET ignores the years and returns the last three), with a limit of 25
requests a day. So the series is asked in fixed ten-year windows from 1913:
twelve requests the first time. A window is *final* once it's two years old,
or a year old and past February (December's index comes out in mid-January),
and is then asked once and cached for good. A newer window is asked again each
ISO week (the week is a ``#fragment`` tag on the cache key, never sent), so new
months flow in with the weekly deploy; older answers to it are deleted once a
newer one is cached. If this week's request fails, the newest cached answer is
used and the report says so.

A month BLS has no index for (October 2025: "Data unavailable due to the 2025
lapse in appropriations") is interpolated between its neighbours at build time
and flagged ``is_interpolated``, so every month has a value to price with.

FRED is deliberately not used: its terms of use bar scraping and caching FRED
content, and its API needs a registered key.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl

from .. import paths
from ..fetch import Fetcher, FetchDisabledError, FetchError, default_fetcher

SERIES = "CUUR0000SA0"
API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
FIRST_YEAR = 1913
WINDOW_YEARS = 10  # v1's most per request
BASE = "1982-84=100"  # the index's own reference period
SCHEMA = {"month": pl.Date, "cpi": pl.Float64, "is_interpolated": pl.Boolean}
REPORT = "cpi_report.json"
MONTH_RE = re.compile(r"M(0[1-9]|1[0-2])")  # M13 is the annual average


def windows(today: date) -> list[tuple[int, int]]:
    """Ten-year windows from FIRST_YEAR through this year (the last one may be shorter)."""
    out = []
    for start in range(FIRST_YEAR, today.year + 1, WINDOW_YEARS):
        out.append((start, min(start + WINDOW_YEARS - 1, today.year)))
    return out


def is_final(window: tuple[int, int], today: date) -> bool:
    """Every month of the window is published (December's index comes out in mid-January)."""
    end = window[1]
    return end <= today.year - 2 or (end == today.year - 1 and today.month >= 3)


def week_tag(today: date) -> str:
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}"


def body(window: tuple[int, int]) -> bytes:
    return json.dumps({"seriesid": [SERIES], "startyear": str(window[0]), "endyear": str(window[1])},
                      separators=(",", ":")).encode("utf-8")


def request_url(window: tuple[int, int], today: date) -> str:
    return API if is_final(window, today) else f"{API}#{week_tag(today)}"


def _series(doc: dict) -> dict:
    results = doc.get("Results")
    series = results.get("series") if isinstance(results, dict) else None
    if not series:
        raise ValueError(f"no series in the answer: {doc.get('message')}")
    return series[0]


def validate(raw: bytes) -> None:
    """Refuse anything but a successful answer for our series (a 'daily threshold' reply is a 200)."""
    doc = json.loads(raw)
    if doc.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError(f"BLS answered {doc.get('status')}: {doc.get('message')}")
    s = _series(doc)
    if s.get("seriesID") != SERIES:
        raise ValueError(f"answer is for series {s.get('seriesID')}, not {SERIES}")


def parse(raw: bytes) -> tuple[list[tuple[date, float]], dict[date, str]]:
    """(month, index) for every monthly value in an answer, and the months listed without one
    (BLS gives "-" and a footnote saying why)."""
    out, unavailable = [], {}
    for row in _series(json.loads(raw)).get("data") or []:
        m = MONTH_RE.fullmatch(row.get("period", ""))
        if not m:
            continue
        try:
            month = date(int(row["year"]), int(m.group(1)), 1)
        except (KeyError, TypeError, ValueError):
            continue
        try:
            out.append((month, float(row["value"])))
        except (KeyError, TypeError, ValueError):
            notes = [f.get("text") for f in row.get("footnotes") or [] if isinstance(f, dict) and f.get("text")]
            unavailable[month] = "; ".join(notes) or f"no value ({row.get('value')!r})"
    return out, unavailable


def _next_month(m: date) -> date:
    return date(m.year + m.month // 12, m.month % 12 + 1, 1)


def series(values: dict[date, float]) -> pl.DataFrame:
    """Every month from the first to the last, a month without an index interpolated linearly
    between the published months around it (rounded to BLS's three decimals) and flagged."""
    if not values:
        return pl.DataFrame(schema=SCHEMA)
    known = sorted(values)
    rows, m, i = [], known[0], 0
    while m <= known[-1]:
        if m in values:
            rows.append((m, values[m], False))
            i += 1
        else:
            before, after = known[i - 1], known[i]
            span = (after.year - before.year) * 12 + after.month - before.month
            step = (m.year - before.year) * 12 + m.month - before.month
            rows.append((m, round(values[before] + (values[after] - values[before]) * step / span, 3), True))
        m = _next_month(m)
    return pl.DataFrame(rows, schema=SCHEMA, orient="row")


@dataclass(frozen=True)
class Entry:
    window: tuple[int, int]
    tag: str  # "" for a final window's answer
    path: Path


def cached_entries() -> list[Entry]:
    """Every complete CPI answer in the raw cache."""
    directory = paths.data_raw() / "http" / "api.bls.gov"
    out = []
    if not directory.is_dir():
        return out
    for meta in sorted(directory.glob("*.meta.json")):
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
            req = json.loads(m.get("post_body") or "{}")
        except (OSError, json.JSONDecodeError):
            continue
        url = m.get("url", "")
        if not url.startswith(API) or req.get("seriesid") != [SERIES]:
            continue
        b = meta.with_name(meta.name.removesuffix(".meta.json"))
        if b.is_file():  # the body is written last: it marks a complete entry
            tag = url.partition("#")[2]
            out.append(Entry((int(req["startyear"]), int(req["endyear"])), tag, b))
    return out


def _newest(entries: list[Entry], window: tuple[int, int]) -> Entry | None:
    """The best cached answer for a window: a final one, else the latest week's."""
    own = [e for e in entries if e.window == window]
    final = [e for e in own if not e.tag]
    if final:
        return final[0]
    return max(own, key=lambda e: e.tag, default=None)


def prune(entries: list[Entry], keep: dict[tuple[int, int], Entry]) -> int:
    """Delete cached answers that a better one for the same window replaced, and answers for
    windows no longer asked (this year's window grows by a year each January)."""
    removed = 0
    for e in entries:
        best = keep.get(e.window)
        if best is None or e.path != best.path:
            e.path.with_name(e.path.name + ".meta.json").unlink(missing_ok=True)
            e.path.unlink(missing_ok=True)
            removed += 1
    return removed


@dataclass
class Result:
    table: pl.DataFrame
    report: dict


def ingest(fetcher: Fetcher, today: date, log=print) -> Result:
    """Fetch what's missing or due, then combine the newest answer for each window."""
    wanted = windows(today)
    stopped = None
    fetched = []
    for w in wanted:
        url = request_url(w, today)
        if fetcher.is_cached(url, post=body(w)):
            continue
        try:
            fetcher.fetch(url, post=body(w), suffix=".json", validate=validate)
            fetched.append(f"{w[0]}-{w[1]}")
        except FetchDisabledError:
            stopped = "fetching disabled"
            break
        except FetchError as exc:
            stopped = f"error: {exc}"
            log(f"  cpi: {exc}")
            break
    entries = cached_entries()
    chosen = {w: e for w in wanted if (e := _newest(entries, w)) is not None}
    missing = [w for w in wanted if w not in chosen]
    if missing:
        what = ", ".join(f"{a}-{b}" for a, b in missing)
        if stopped == "fetching disabled" or not stopped:
            raise FetchDisabledError(f"BLS CPI for {what} is not cached in data/raw/")
        raise FetchError(f"BLS CPI for {what} could not be fetched ({stopped})")
    values: dict[date, float] = {}
    unavailable: dict[date, str] = {}
    for w in wanted:
        got, gaps = parse(chosen[w].path.read_bytes())
        values.update(got)
        unavailable.update(gaps)
    table = series(values)
    interpolated = [{"month": m.isoformat()[:7], "cpi": v, "note": unavailable.get(m, "not in BLS's answer")}
                    for m, v, flag in table.iter_rows() if flag]
    tag = week_tag(today)
    stale = [f"{w[0]}-{w[1]} ({e.tag})" for w, e in chosen.items() if e.tag and e.tag != tag]
    pruned = prune(entries, chosen) if not stopped else 0
    report = {
        "series": SERIES,
        "base": BASE,
        "built_on": today.isoformat(),
        "months": table.height,
        "first_month": table["month"].min().isoformat() if table.height else None,
        "latest_month": table["month"].max().isoformat() if table.height else None,
        "latest_cpi": table["cpi"].to_list()[-1] if table.height else None,
        "windows": len(wanted),
        "fetched": fetched,
        "fetch": {"stopped": stopped},
        "stale_windows": stale,
        "interpolated_months": interpolated,
        "pruned_cache_entries": pruned,
        "network_requests": fetcher.network_requests,
    }
    return Result(table, report)


def run(fetcher: Fetcher | None = None, today: date | None = None) -> Path:
    """Source step: write data/build/cpi.parquet and cpi_report.json."""
    fetcher = fetcher or default_fetcher
    today = today or datetime.now(timezone.utc).date()
    result = ingest(fetcher, today)
    build_dir = paths.data_build()
    build_dir.mkdir(parents=True, exist_ok=True)
    out = build_dir / "cpi.parquet"
    result.table.write_parquet(out)
    (build_dir / REPORT).write_text(json.dumps(result.report, indent=2) + "\n", encoding="utf-8")
    r = result.report
    print(f"  cpi: {SERIES} {r['first_month']} to {r['latest_month']} ({r['months']} months, latest "
          f"{r['latest_cpi']}); {len(r['fetched'])} of {r['windows']} windows fetched; "
          f"stale {r['stale_windows'] or 'none'}; {r['network_requests']} requests")
    return out
