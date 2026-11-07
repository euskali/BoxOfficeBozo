"""M2: Box Office Mojo weekend charts, 2017 -> present.

Archives ONLY: captures are located through the Wayback Machine CDX API and
the Common Crawl index, then fetched from web.archive.org / data.commoncrawl.org.
There is no live backend; boxofficemojo.com is hard-blocked in
``boffo_etl.fetch``.

For each weekend after stat695data's last one, through the latest completed
weekend:

1. Wayback, new-style page ``/weekend/{YYYY}W{WW}/`` (one exact CDX query per
   time window, see :func:`cdx_windows`). The capture closest after the
   weekend's Monday + 7 days wins (actuals, not Sunday estimates); failing
   that, the latest one between that Monday and then.
2. Wayback, old-style chart URLs captured at the time (weekends before the
   October 2019 redesign).
3. Common Crawl: the same URLs in the crawl indexes, read as one WARC record
   by byte range.

Box Office Mojo numbers weekends by Friday: ``2020W01`` is the weekend of the
year's first Friday. Weekends with no usable capture are listed in
``bom_weekend_weekends.csv`` for the checks.py gap report.

Stitching: new-style pages key films by ``rl`` release ids, stat695data by
legacy ids. The last few stat695 weekends are also fetched as new-style
pages, and their rows are matched to the stat695 rows of the same weekend by
gross. A matched ``rl`` release continues the legacy release (same
release_id), so carry-over films keep one continuous total_gross.
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

import polars as pl
from rapidfuzz import fuzz

from .. import archives, paths
from ..archives import Capture
from ..fetch import Fetcher, FetchDisabledError, FetchError, default_fetcher
from . import bom_pages
from .bom_pages import ChartPage, NotAChart
from .stat695 import (
    RELEASE_ID_PREFIX as LEGACY_PREFIX,
    RELEASE_SCHEMA,
    REISSUE_RE,
    SNAPSHOT_SCHEMA,
    normalize_title,
    provisional_title_ids,
    split_title,
)

SOURCE = "bom_weekend"
RELEASE_PREFIX = "bom:"
NEW_URL = "https://www.boxofficemojo.com/weekend/{code}/"
OLD_URLS = (
    "http://www.boxofficemojo.com/weekend/chart/?yr={year}&wknd={week:02d}&p=.htm",
    "http://www.boxofficemojo.com/weekend/chart/?view=&yr={year}&wknd={week:02d}&p=.htm",
)
RELEASE_URL = "https://www.boxofficemojo.com/release/{rl}/"
OLD_SITE_LAST = date(2019, 11, 3)  # the old chart pages stop with the Oct 2019 redesign
NEW_SITE_FROM = date(2019, 10, 1)  # no new-style page was captured before the redesign
OLD_SITE_CAPTURED_BY = "20191231"
DEFAULT_BOUNDARY = date(2017, 1, 1)  # stat695data's last weekend, if its tables aren't built

SETTLE = timedelta(days=60)  # captures this soon after a weekend are final enough to cache forever
LONG_WINDOW = timedelta(days=6 * 365 + 2)  # new-style pages of 2017-2019 weekends were captured years later
PREFERRED_AFTER = timedelta(days=8)  # Sunday + 8 days = the following Monday: actuals are out
CC_WINDOW = timedelta(days=2 * 365)
MAX_PAGE_TRIES = 3
OVERLAP_WEEKENDS = 4
CONTINUITY_WEEKS = 52
TITLE_MATCH = 90  # rapidfuzz ratio on normalized titles

ENV_MINUTES = "BOFFO_FETCH_MINUTES"
ENV_RELEASE_PAGES = "BOFFO_RELEASE_PAGES"
ENV_RELEASE_MINUTES = "BOFFO_RELEASE_PAGE_MINUTES"
DEFAULT_MINUTES = 270.0
DEFAULT_RELEASE_PAGES = 150
DEFAULT_RELEASE_MINUTES = 45.0
RELEASE_PAGE_MIN_GROSS = 1_000_000  # smaller releases are left to M3's title matching
CC_INDEX_BUDGET = 60
RETRY_PAUSE = 60.0  # seconds before failed lookups get their second chance

OK, EMPTY, NO_CAPTURE, UNCHECKED, ERROR, PENDING = "ok", "empty_chart", "no_capture", "unchecked", "error", "pending"
# Statuses that the gap report accepts as "no data for this weekend".
EXPLAINED_GAPS = (EMPTY, NO_CAPTURE)


# --- weekend codes -------------------------------------------------------------

def first_friday(year: int) -> date:
    d = date(year, 1, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def weekend_code(sunday: date) -> str:
    friday = sunday - timedelta(days=2)
    n = (friday - first_friday(friday.year)).days // 7 + 1
    return f"{friday.year}W{n:02d}"


def code_sunday(code: str) -> date:
    m = re.fullmatch(r"(\d{4})W(\d{2})", code)
    if not m:
        raise ValueError(f"bad weekend code {code!r}")
    return first_friday(int(m[1])) + timedelta(weeks=int(m[2]) - 1, days=2)


def sunday_on_or_before(d: date) -> date:
    return d - timedelta(days=(d.weekday() + 1) % 7)


def latest_completed_sunday(today: date) -> date:
    """The last Sunday before today (a weekend is complete once Monday starts)."""
    return today - timedelta(days=((today.weekday() + 1) % 7) or 7)


def _utc(d: date) -> datetime:
    return datetime.combine(d, dtime(), tzinfo=timezone.utc)


def cdx_windows(sunday: date, today: date, *, not_before: date | None = None) -> list[tuple[str, str]]:
    """CDX (from, to) windows to try in order for one weekend.

    Windows that already ended are fixed URLs, cached for good. The last one
    is open: it ends today (re-asked daily) for a weekend under 60 days old,
    else this month (re-asked monthly, so a newly archived page still turns up).
    Fixed windows that end before ``not_before`` can't hold a capture and are skipped.
    """
    monday = sunday + timedelta(days=1)
    start = monday.strftime("%Y%m%d")
    out = []
    for span in (SETTLE, LONG_WINDOW):
        end = monday + span
        if end < today and (not_before is None or end >= not_before):
            out.append((start, end.strftime("%Y%m%d")))
    open_to = today.strftime("%Y%m%d") if monday + SETTLE >= today else today.strftime("%Y%m")
    out.append((start, open_to))
    return out


# --- locating and fetching one weekend -----------------------------------------

class BudgetExhausted(Exception):
    """This run's fetch time (or Common Crawl index allowance) is used up."""


@dataclass
class Budget:
    deadline: float
    cc_queries: int = CC_INDEX_BUDGET

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise BudgetExhausted("fetch time budget used up")


@dataclass
class WeekendResult:
    code: str
    sunday: date
    status: str
    archive: str | None = None
    style: str | None = None
    capture: Capture | None = None
    capture_url: str | None = None
    page: ChartPage | None = None
    notes: list[str] = field(default_factory=list)


class Locator:
    def __init__(self, fetcher: Fetcher, today: date, budget: Budget) -> None:
        self.fetcher = fetcher
        self.today = today
        self.budget = budget
        self._crawls: list[archives.Crawl] | None = None
        self._crawls_error: str | None = None

    # network, through the cache
    def _get(self, url: str, **kw) -> Path:
        if not self.fetcher.is_cached(url):
            self.budget.check()
        return self.fetcher.fetch(url, **kw)

    def _get_range(self, url: str, start: int, length: int) -> Path:
        if not self.fetcher.is_cached(url, byte_range=(start, length)):
            self.budget.check()
        return self.fetcher.fetch_range(url, start, length, suffix=".warc.gz")

    def wayback_captures(self, target: str, start: str, to: str) -> list[Capture]:
        url = archives.wayback_cdx_url(target, start=start, to=to)
        path = self._get(url, suffix=".json", validate=archives.validate_wayback_cdx)
        return archives.parse_wayback_cdx(path.read_bytes())

    @staticmethod
    def _check_page(page: ChartPage, code: str, sunday: date) -> str | None:
        if page.end is not None and page.end != sunday:
            return f"page covers {page.start} to {page.end}, not the weekend ending {sunday}"
        if page.style == "new" and f"{page.year}W{page.week:02d}" != code:
            return f"page heading says {page.year}W{page.week:02d}"
        if page.end is None and page.style == "old":
            return "page has no weekend dates"
        return None

    def _try_pages(self, res: WeekendResult, candidates: list[Capture], style: str) -> bool:
        parse = bom_pages.parse_new_weekend if style == "new" else bom_pages.parse_old_weekend
        for c in candidates[:MAX_PAGE_TRIES]:
            try:
                if c.archive == "wayback":
                    html = archives.decode_html(self._get(archives.wayback_raw_url(c), suffix=".html").read_bytes())
                    view = archives.wayback_view_url(c)
                else:
                    raw = self._get_range(archives.cc_record_url(c), c.offset, c.length).read_bytes()
                    status, _, body = archives.parse_warc_record(raw)
                    if status != 200:
                        res.notes.append(f"{c.crawl} record is HTTP {status}")
                        continue
                    html = archives.decode_html(body)
                    view = archives.cc_view_url(c)
                page = parse(html)
            except (FetchDisabledError, BudgetExhausted):
                raise
            except NotAChart as exc:
                res.notes.append(f"{c.archive} {c.ts14}: not a chart ({exc})")
                continue
            except Exception as exc:  # a failed fetch, a broken WARC record, undecodable bytes
                res.notes.append(f"{c.archive} {c.ts14}: {type(exc).__name__}: {exc}")
                continue
            problem = self._check_page(page, res.code, res.sunday)
            if problem:
                res.notes.append(f"{c.archive} {c.ts14}: {problem}")
                continue
            res.status = OK if page.rows else EMPTY
            res.archive, res.style, res.capture, res.capture_url, res.page = c.archive, style, c, view, page
            return True
        return False

    def _wayback(self, res: WeekendResult, targets: list[str], windows: list[tuple[str, str]], style: str) -> bool:
        earliest = _utc(res.sunday + timedelta(days=1))
        preferred = _utc(res.sunday + PREFERRED_AFTER)
        fallback: list[Capture] = []
        chosen: list[Capture] | None = None
        for start, to in windows:
            caps = [c for t in targets for c in self.wayback_captures(t, start, to)]
            ordered = archives.order_candidates(caps, earliest=earliest, preferred_after=preferred)
            if any(c.timestamp >= preferred for c in ordered):
                chosen = ordered
                break
            fallback = ordered or fallback
        return self._try_pages(res, chosen if chosen is not None else fallback, style)

    def crawls(self) -> list[archives.Crawl]:
        if self._crawls is None:
            url = archives.cc_collinfo_url(self.today.strftime("%Y%m"))
            path = self._get(url, suffix=".json", validate=archives.validate_collinfo)
            self._crawls = archives.parse_collinfo(path.read_bytes())
        return self._crawls

    def _commoncrawl(self, res: WeekendResult, targets: list[tuple[str, str]]) -> bool:
        """``targets`` are (url, style). Raises FetchError if the index can't be read."""
        monday = res.sunday + timedelta(days=1)
        lo, hi = _utc(monday), _utc(monday + CC_WINDOW)
        for crawl in [c for c in self.crawls() if c.end >= lo and c.start <= hi]:
            for target, style in targets:
                url = archives.cc_index_url(crawl, target)
                if not self.fetcher.is_cached(url):
                    if self.budget.cc_queries <= 0:
                        raise BudgetExhausted("Common Crawl index allowance used up")
                    self.budget.cc_queries -= 1
                path = self._get(url, suffix=".json", accept_status=(200, 404), validate=archives.validate_cc_index)
                caps = [replace(c, crawl=crawl.id) for c in archives.parse_cc_index(path.read_bytes())]
                ordered = archives.order_candidates(caps, earliest=_utc(monday),
                                                    preferred_after=_utc(res.sunday + PREFERRED_AFTER))
                ordered = [c for c in ordered if c.filename and c.offset is not None and c.length]
                if ordered and self._try_pages(res, ordered, style):
                    return True
        return False

    def locate(self, code: str, *, allow_old: bool = True, allow_cc: bool = True) -> WeekendResult:
        sunday = code_sunday(code)
        res = WeekendResult(code, sunday, NO_CAPTURE)
        year, week = int(code[:4]), int(code[5:])
        errors = 0
        try:
            new_target = NEW_URL.format(code=code)
            try:
                windows = cdx_windows(sunday, self.today, not_before=NEW_SITE_FROM)
                if self._wayback(res, [new_target], windows, "new"):
                    return res
            except FetchError as exc:
                if isinstance(exc, FetchDisabledError):
                    raise
                errors += 1
                res.notes.append(f"wayback lookup failed: {exc}")
            old_targets = [u.format(year=year, week=week) for u in OLD_URLS]
            use_old = allow_old and sunday <= OLD_SITE_LAST
            if use_old:
                try:
                    window = [((sunday + timedelta(days=1)).strftime("%Y%m%d"), OLD_SITE_CAPTURED_BY)]
                    if self._wayback(res, old_targets, window, "old"):
                        return res
                except FetchError as exc:
                    if isinstance(exc, FetchDisabledError):
                        raise
                    errors += 1
                    res.notes.append(f"wayback old-style lookup failed: {exc}")
            if not allow_cc:
                res.status = ERROR if errors else NO_CAPTURE
                return res
            try:
                cc_targets = [(new_target, "new")] + ([(t, "old") for t in old_targets] if use_old else [])
                if self._commoncrawl(res, cc_targets):
                    return res
            except FetchError as exc:
                if isinstance(exc, FetchDisabledError):
                    raise
                res.status = ERROR if errors else UNCHECKED
                res.notes.append(f"common crawl index unavailable: {exc}")
                return res
            res.status = ERROR if errors else NO_CAPTURE
            return res
        except BudgetExhausted as exc:
            res.status = PENDING
            res.notes.append(str(exc))
            return res


# --- rows ------------------------------------------------------------------------

def result_rows(res: WeekendResult) -> list[dict]:
    if res.page is None:
        return []
    out = []
    after = res.capture.timestamp >= _utc(res.sunday + timedelta(days=2)) if res.capture else False
    for r in res.page.rows:
        est = r.is_estimate
        if est is None and res.style == "old" and after:
            est = False  # old pages had no estimate flag; by Tuesday the chart showed actuals
        out.append({
            "code": res.code, "weekend_end": res.sunday, "style": res.style, "key": r.key, "rank": r.rank,
            "title": r.title, "label": r.label, "weekend_gross": r.weekend_gross, "theaters": r.theaters,
            "total_gross": r.total_gross, "weeks": r.weeks, "distributor": r.distributor, "is_new": r.is_new,
            "is_estimate": est, "source": res.archive, "capture_url": res.capture_url,
        })
    return out


ROW_SCHEMA = {
    "code": pl.String, "weekend_end": pl.Date, "style": pl.String, "key": pl.String, "rank": pl.Int32,
    "title": pl.String, "label": pl.String, "weekend_gross": pl.Int64, "theaters": pl.Int32,
    "total_gross": pl.Int64, "weeks": pl.Int32, "distributor": pl.String, "is_new": pl.Boolean,
    "is_estimate": pl.Boolean, "source": pl.String, "capture_url": pl.String,
}


def rows_frame(results: list[WeekendResult]) -> pl.DataFrame:
    return pl.DataFrame([r for res in results for r in result_rows(res)], schema=ROW_SCHEMA)


# --- stitching to stat695data ---------------------------------------------------------

_YEAR_SUFFIX_RE = re.compile(r"\s*\((?:19|20)\d{2}\)\s*$")
BIG_WEEKEND = 100_000  # an exactly equal weekend gross this big on the same weekend is the same film


def _base(title: str | None) -> str:
    """Comparable title: no re-release suffix, no "(2016)" disambiguator, normalized."""
    return normalize_title(_YEAR_SUFFIX_RE.sub("", split_title(title or "")[0]))


def title_similarity(a: str | None, b: str | None) -> float:
    x, y = _base(a), _base(b)
    return fuzz.ratio(x, y) if x and y else 0.0


def _close(a: int | None, b: int | None, tol: float) -> bool:
    return bool(a) and bool(b) and abs(a - b) <= tol * max(a, b)


def _pair_tier(leg: dict, new: dict) -> tuple[int, float] | None:
    """How strongly a stat695 row and a new-style row on the same weekend look like one film
    (0 strongest), or None. Box Office Mojo renamed some films on the new site, so big equal
    grosses count without the title."""
    sim = title_similarity(leg["title"], new["title"])
    wg, tg = leg["weekend_gross"], leg["total_gross"]
    wg_equal = wg is not None and wg == new["weekend_gross"]
    tg_equal = tg is not None and tg == new["total_gross"]
    if wg_equal and (tg_equal or sim >= 80):
        return 0, sim
    if tg_equal and (sim >= 60 or _close(wg, new["weekend_gross"], 0.01)):
        return 1, sim
    if wg_equal and wg >= BIG_WEEKEND:
        return 2, sim
    if sim >= TITLE_MATCH and _close(wg, new["weekend_gross"], 0.02):
        return 3, sim
    if (leg.get("rank") is not None and leg.get("rank") == new.get("rank")
            and _close(wg, new["weekend_gross"], 0.01) and _close(tg, new["total_gross"], 0.01)):
        return 4, sim
    return None


def match_weekend(legacy_rows: list[dict], new_rows: list[dict]) -> list[tuple[str, str, int]]:
    """One weekend, both sources -> (legacy release_id, rl id, tier) pairs, one-to-one."""
    pairs = []
    for leg in legacy_rows:
        for new in new_rows:
            t = _pair_tier(leg, new)
            if t is not None:
                pairs.append((t[0], -t[1], leg["release_id"], new["key"]))
    pairs.sort()
    used_l: set[str] = set()
    used_n: set[str] = set()
    out = []
    for tier, _, lid, rl in pairs:
        if lid in used_l or rl in used_n:
            continue
        used_l.add(lid)
        used_n.add(rl)
        out.append((lid, rl, tier))
    return out


@dataclass
class Link:
    rl: str
    release_id: str
    method: str  # "overlap" | "continuity"
    weekends: int  # overlap weekends that matched
    detail: str


def link_overlap(overlap: pl.DataFrame, legacy_snaps: pl.DataFrame) -> tuple[dict[str, Link], list[str]]:
    """Match the overlap weekends' new-style rows to stat695 rows. Returns links and conflicts."""
    votes: dict[str, Counter] = defaultdict(Counter)
    tiers: dict[tuple[str, str], int] = {}
    for sunday in overlap["weekend_end"].unique().sort().to_list():
        new_rows = overlap.filter(pl.col("weekend_end") == sunday).to_dicts()
        leg_rows = legacy_snaps.filter(pl.col("sunday") == sunday).to_dicts()
        for lid, rl, tier in match_weekend(leg_rows, new_rows):
            votes[rl][lid] += 1
            tiers[(rl, lid)] = min(tier, tiers.get((rl, lid), 9))
    links: dict[str, Link] = {}
    conflicts: list[str] = []
    for rl, counter in votes.items():
        (lid, n), *rest = counter.most_common()
        if rest and rest[0][1] == n:
            conflicts.append(f"{rl}: tied between {lid} and {rest[0][0]}")
            continue
        links[rl] = Link(rl, lid, "overlap", n, f"best tier {tiers[(rl, lid)]}")
    by_legacy: dict[str, list[Link]] = defaultdict(list)
    for link in links.values():
        by_legacy[link.release_id].append(link)
    for lid, ls in by_legacy.items():
        if len(ls) > 1:
            ls.sort(key=lambda x: -x.weekends)
            for loser in ls[1:]:
                conflicts.append(f"{loser.rl}: {lid} is also matched by {ls[0].rl}")
                del links[loser.rl]
    return links, conflicts


def link_continuity(main: pl.DataFrame, legacy_last: pl.DataFrame, links: dict[str, Link],
                    boundary: date) -> dict[str, Link]:
    """Link rl releases that were already in release at their first chart here (weeks > 1)
    to a stat695 release with the same title that charted shortly before, if totals carry on."""
    linked_legacy = {link.release_id for link in links.values()}
    firsts = (main.filter(pl.col("style") == "new").sort("weekend_end")
              .group_by("key", maintain_order=True).first())
    cands = legacy_last.filter(pl.col("last_weekend") >= boundary - timedelta(weeks=CONTINUITY_WEEKS)).to_dicts()
    out: dict[str, Link] = {}
    for r in firsts.to_dicts():
        rl = r["key"]
        if rl in links or not r["weeks"] or r["weeks"] <= 1:
            continue
        if r["weekend_end"] > boundary + timedelta(weeks=CONTINUITY_WEEKS):
            continue
        found = []
        for c in cands:
            if c["release_id"] in linked_legacy or title_similarity(c["title"], r["title"]) < TITLE_MATCH:
                continue
            if c["total_gross"] is not None and r["total_gross"] is not None and r["total_gross"] < c["total_gross"]:
                continue
            if c["weeks"] is not None:  # weeks in release must have moved on by about the time elapsed
                elapsed = (r["weekend_end"] - c["last_weekend"]).days // 7
                if not c["weeks"] < r["weeks"] <= c["weeks"] + elapsed + 1:
                    continue
            found.append(c)
        if len(found) == 1:
            c = found[0]
            out[rl] = Link(rl, c["release_id"], "continuity", 0,
                           f"{c['last_weekend']} total {c['total_gross']} -> {r['weekend_end']} total {r['total_gross']}")
            linked_legacy.add(c["release_id"])
    return out


# --- releases and snapshots ----------------------------------------------------------

def _is_reissue_label(label: str | None) -> bool:
    return bool(label) and bool(REISSUE_RE.search(label))


def assign_releases(
    rows: pl.DataFrame,
    links: dict[str, Link],
    legacy_releases: pl.DataFrame,
    release_info: dict[str, bom_pages.ReleaseInfo],
) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    """Rows (main weekends) -> (snapshots, new releases, stats)."""
    legacy_ids = set(legacy_releases["release_id"].to_list()) if legacy_releases.height else set()
    legacy_tid = dict(zip(legacy_releases["release_id"].to_list(), legacy_releases["title_id"].to_list())) \
        if legacy_releases.height else {}
    stats: dict = {"old_style_rows": 0, "old_style_to_legacy": 0, "old_style_to_rl": 0, "old_style_new": 0}

    # Old-style rows carry legacy ids: stat695's own, or new ones; the latter join an rl release
    # with the same title charting within a month, if there is exactly one.
    new_rows = rows.filter(pl.col("style") == "new")
    rl_by_title: dict[str, list[tuple[date, str]]] = defaultdict(list)
    for r in new_rows.select("key", "title", "weekend_end").unique().to_dicts():
        rl_by_title[_base(r["title"])].append((r["weekend_end"], r["key"]))
    old_map: dict[str, str] = {}
    for r in rows.filter(pl.col("style") == "old").select("key", "title", "weekend_end").to_dicts():
        stats["old_style_rows"] += 1
        lid = LEGACY_PREFIX + r["key"]
        if lid in legacy_ids:
            old_map.setdefault(r["key"], lid)
            continue
        near = {rl for d, rl in rl_by_title.get(_base(r["title"]), []) if abs((d - r["weekend_end"]).days) <= 28}
        if len(near) == 1 and r["key"] not in old_map:
            old_map[r["key"]] = "rl:" + near.pop()
    for key, target in list(old_map.items()):
        if target.startswith("rl:"):
            rl = target[3:]
            old_map[key] = links[rl].release_id if rl in links else RELEASE_PREFIX + rl

    def release_id(style: str, key: str) -> str:
        if style == "new":
            return links[key].release_id if key in links else RELEASE_PREFIX + key
        return old_map.get(key, LEGACY_PREFIX + key)

    rid = [release_id(s, k) for s, k in zip(rows["style"].to_list(), rows["key"].to_list())]
    rows = rows.with_columns(pl.Series("release_id", rid, dtype=pl.String))
    for s, r in zip(rows["style"].to_list(), rid):
        if s == "old":
            if r in legacy_ids:
                stats["old_style_to_legacy"] += 1
            elif r.startswith(RELEASE_PREFIX):
                stats["old_style_to_rl"] += 1
            else:
                stats["old_style_new"] += 1

    # New releases: every release_id here that stat695 doesn't already have.
    agg = (
        rows.filter(~pl.col("release_id").is_in(list(legacy_ids)))
        .sort("weekend_end", "rank", nulls_last=True)
        .group_by("release_id", maintain_order=True)
        .agg(
            pl.col("style").first(), pl.col("key").first(),
            pl.col("title").drop_nulls().first(), pl.col("label").drop_nulls().first(),
            pl.col("distributor").drop_nulls().first(),
            pl.col("weekend_end").min().alias("first_weekend"), pl.col("weekend_end").max().alias("last_weekend"),
            pl.col("weekend_end").n_unique().cast(pl.Int32).alias("weekends"),
        )
    ).to_dicts()

    # Provisional title_ids, made once per release: rl releases that share an IMDb title on their
    # archived release pages share one (and a stat695 release's, if it's in the group).
    by_tt: dict[str, list[str]] = defaultdict(list)
    first_of: dict[str, date] = {}
    for link in links.values():
        info = release_info.get(link.rl)
        if info and info.tt_id:
            by_tt[info.tt_id].append(link.release_id)
    for a in agg:
        first_of[a["release_id"]] = a["first_weekend"]
        info = release_info.get(a["key"]) if a["style"] == "new" else None
        if info and info.tt_id:
            by_tt[info.tt_id].append(a["release_id"])
    taken = set(legacy_tid.values())
    legacy_new = provisional_title_ids([a["key"] for a in agg if a["style"] == "old"])
    tid: dict[str, str] = {}
    for a in agg:
        if a["style"] == "new":
            tid[a["release_id"]] = f"bb_{a['key'].lower()}"
        else:
            t = legacy_new[a["key"]]
            tid[a["release_id"]] = t if t not in taken else f"{t}_bom"
    parent: dict[str, str | None] = {}
    for tt, members in by_tt.items():
        members = sorted(set(members), key=lambda m: (m not in legacy_ids, first_of.get(m, date.min), m))
        root = members[0]
        root_tid = legacy_tid.get(root) or tid.get(root)
        for m in members:
            if m in tid:
                tid[m] = root_tid
                parent[m] = root if m != root else None

    releases = []
    for a in agg:
        info = release_info.get(a["key"]) if a["style"] == "new" else None
        kind = split_title(a["title"] or "")[2]
        if _is_reissue_label(a["label"]):
            reason = "bom_label"
        elif kind == "reissue":
            reason = "title_keyword"
        else:
            reason = None
        releases.append({
            "release_id": a["release_id"],
            "title_id": tid[a["release_id"]],
            "label": a["label"],
            "release_date": info.release_date if info else None,
            "source_key": a["key"],
            "source": SOURCE,
            "title": a["title"],
            "distributor": a["distributor"] or (info.distributor if info else None),
            "genres": info.genres if info else None,
            "mpaa": info.mpaa if info else None,
            "first_weekend": a["first_weekend"],
            "last_weekend": a["last_weekend"],
            "weekends": a["weekends"],
            "is_rerelease": reason is not None,
            "rerelease_reason": reason,
            "parent_release_id": parent.get(a["release_id"]) if reason else None,
            "group_source": "auto",
        })
    rel_df = pl.DataFrame(releases, schema=RELEASE_SCHEMA).sort("first_weekend", "release_id")

    title_of = {**legacy_tid, **tid}
    snaps = (
        rows.with_columns(pl.col("release_id").replace_strict(title_of, default=None).alias("title_id"))
        .sort("weekend_end", "rank", "release_id", nulls_last=True)
    )
    # A release charted twice on one weekend (an old-style id joined to an rl release): keep the first.
    before = snaps.height
    snaps = snaps.unique(["weekend_end", "release_id"], keep="first", maintain_order=True)
    stats["duplicate_rows_dropped"] = before - snaps.height
    snapshots = snaps.select(list(SNAPSHOT_SCHEMA)).cast(SNAPSHOT_SCHEMA)
    return snapshots, rel_df, stats


# --- release pages (IMDb tt ids for M3) ----------------------------------------------------

RELEASE_PAGE_SCHEMA = {
    "rl_id": pl.String, "status": pl.String, "tt_id": pl.String, "title": pl.String, "release_date": pl.Date,
    "mpaa": pl.String, "genres": pl.String, "running_time": pl.String, "distributor": pl.String,
    "capture_url": pl.String,
}


def release_pages(fetcher: Fetcher, rls: list[str], *, lookups: int, deadline: float) -> tuple[list[dict], dict]:
    """Read archived release pages, best first. Cached ones are always read; at most ``lookups``
    new CDX lookups are made, and none after ``deadline``."""
    out, stats = [], {"cached": 0, "fetched": 0, "not_reached": 0, "no_capture": 0, "errors": 0}
    for rl in rls:
        target = RELEASE_URL.format(rl=rl)
        cdx = archives.wayback_cdx_url(target)
        cached = fetcher.is_cached(cdx)
        if not cached and (lookups <= 0 or time.monotonic() > deadline):
            stats["not_reached"] += 1
            continue
        try:
            if not cached:
                lookups -= 1
            caps = archives.parse_wayback_cdx(
                fetcher.fetch(cdx, suffix=".json", validate=archives.validate_wayback_cdx).read_bytes())
            caps = sorted((c for c in caps if c.is_html), key=lambda c: c.timestamp, reverse=True)
            if not caps:
                stats["no_capture"] += 1
                out.append({"rl_id": rl, "status": NO_CAPTURE})
                continue
            row = None
            for c in caps[:2]:
                raw = archives.wayback_raw_url(c)
                if not fetcher.is_cached(raw) and time.monotonic() > deadline:
                    break
                try:
                    info = bom_pages.parse_release_page(
                        archives.decode_html(fetcher.fetch(raw, suffix=".html").read_bytes()))
                except FetchDisabledError:
                    raise
                except (NotAChart, FetchError):
                    continue
                row = {"rl_id": rl, "status": OK, **{k: getattr(info, k) for k in (
                    "tt_id", "title", "release_date", "mpaa", "genres", "running_time", "distributor")},
                    "capture_url": archives.wayback_view_url(c)}
                break
            if row is None:
                stats["errors"] += 1
                continue
            stats["cached" if cached else "fetched"] += 1
            out.append(row)
        except FetchDisabledError:
            stats["not_reached"] += 1
        except FetchError:
            stats["errors"] += 1
    return out, stats


# --- the build step -----------------------------------------------------------------------

@dataclass
class Ingest:
    snapshots: pl.DataFrame
    releases: pl.DataFrame
    links: pl.DataFrame
    weekends: list[WeekendResult]
    release_pages: pl.DataFrame
    report: dict


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _legacy_inputs(build_dir: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    sp, rp = build_dir / "stat695_snapshots.parquet", build_dir / "stat695_releases.parquet"
    if not (sp.is_file() and rp.is_file()):
        return pl.DataFrame(schema=SNAPSHOT_SCHEMA), pl.DataFrame(schema=RELEASE_SCHEMA)
    return pl.read_parquet(sp), pl.read_parquet(rp)


def ingest(
    fetcher: Fetcher,
    today: date,
    legacy_snaps: pl.DataFrame,
    legacy_releases: pl.DataFrame,
    *,
    minutes: float = DEFAULT_MINUTES,
    release_page_lookups: int = DEFAULT_RELEASE_PAGES,
    release_page_minutes: float = DEFAULT_RELEASE_MINUTES,
    retry_pause: float = RETRY_PAUSE,
    log=print,
) -> Ingest:
    started = time.monotonic()
    budget = Budget(deadline=started + minutes * 60)
    loc = Locator(fetcher, today, budget)

    # Holiday charts in stat695data end on Monday; they count for the Sunday before.
    legacy = legacy_snaps.with_columns(
        (pl.col("weekend_end") - pl.duration(days=pl.col("weekend_end").dt.weekday() % 7)).alias("sunday"))
    if legacy.height:
        boundary = legacy["sunday"].max()
        overlap_sundays = sorted(legacy["sunday"].unique().to_list())[-OVERLAP_WEEKENDS:]
    else:
        boundary, overlap_sundays = DEFAULT_BOUNDARY, []
    latest = latest_completed_sunday(today)
    sundays = []
    d = boundary + timedelta(weeks=1)
    while d <= latest:
        sundays.append(d)
        d += timedelta(weeks=1)
    codes = [weekend_code(s) for s in sundays]
    log(f"  bom_weekend: {len(codes)} weekends {codes[0] if codes else '-'} to {codes[-1] if codes else '-'}, "
        f"{len(overlap_sundays)} overlap weekends with stat695")

    # The first lookup that misses the cache offline raises FetchDisabledError: the step is skipped.
    overlap_results = [loc.locate(weekend_code(s), allow_old=False) for s in overlap_sundays]
    results: list[WeekendResult] = []
    for i, code in enumerate(codes, 1):
        results.append(loc.locate(code))
        if i % 25 == 0 or i == len(codes):
            counts = Counter(r.status for r in results)
            log(f"  bom_weekend: {i}/{len(codes)} weekends, {dict(counts)}, "
                f"{fetcher.network_requests} requests, {(time.monotonic() - started) / 60:.1f} min")

    # The Wayback Machine has bad minutes: failed lookups get one more try after a pause.
    failed = [(lst, i) for lst in (overlap_results, results) for i, r in enumerate(lst) if r.status == ERROR]
    if failed and time.monotonic() < budget.deadline:
        log(f"  bom_weekend: retrying {len(failed)} weekends whose lookups failed")
        time.sleep(retry_pause)
        for lst, i in failed:
            again = loc.locate(lst[i].code, allow_old=lst is results)
            again.notes = lst[i].notes + ["second try: " + (" | ".join(again.notes) or again.status)]
            lst[i] = again
        log(f"  bom_weekend: after retrying, {dict(Counter(r.status for r in results))}")

    main = rows_frame(results)
    overlap = rows_frame(overlap_results)

    # Stitch to stat695data.
    titles = legacy_releases.select("release_id", "title") if legacy_releases.height else \
        pl.DataFrame(schema={"release_id": pl.String, "title": pl.String})
    legacy_rows = legacy.join(titles, on="release_id", how="left")
    links, conflicts = link_overlap(overlap.filter(pl.col("style") == "new"), legacy_rows)
    legacy_last = (legacy_rows.sort("weekend_end").group_by("release_id", maintain_order=True)
                   .agg(pl.col("title").last(), pl.col("weekend_end").max().alias("last_weekend"),
                        pl.col("total_gross").drop_nulls().last(), pl.col("weeks").drop_nulls().last()))
    links.update(link_continuity(main, legacy_last, links, boundary))

    # Archived release pages, best first: stitched carry-overs, then by gross.
    rl_gross = (main.filter(pl.col("style") == "new").group_by("key")
                .agg(pl.col("total_gross").max(), pl.col("weekend_end").min().alias("first")))
    eligible = rl_gross.filter(pl.col("first") <= today - SETTLE).sort("total_gross", descending=True,
                                                                         nulls_last=True)
    eligible_set = set(eligible["key"].to_list())
    order = [rl for rl in links if rl in eligible_set]
    order += [rl for rl in eligible.filter(pl.col("total_gross") >= RELEASE_PAGE_MIN_GROSS)["key"].to_list()
              if rl not in links]
    page_deadline = min(budget.deadline, time.monotonic() + release_page_minutes * 60)
    pages, page_stats = release_pages(fetcher, order, lookups=release_page_lookups, deadline=page_deadline)
    pages_df = pl.DataFrame(pages, schema=RELEASE_PAGE_SCHEMA)
    info = {p["rl_id"]: bom_pages.ReleaseInfo(**{k: p.get(k) for k in (
        "tt_id", "title", "release_date", "mpaa", "genres", "running_time", "distributor")})
        for p in pages if p.get("status") == OK}

    snapshots, releases, stats = assign_releases(main, links, legacy_releases, info)
    links_df = pl.DataFrame(
        [{"release_id": lk.release_id, "bom_release_id": lk.rl, "method": lk.method,
          "overlap_weekends": lk.weekends, "detail": lk.detail} for lk in links.values()],
        schema={"release_id": pl.String, "bom_release_id": pl.String, "method": pl.String,
                "overlap_weekends": pl.Int32, "detail": pl.String},
    ).sort("release_id")

    # Carry-overs: films already in release on the first weekend here. One that stat695 charted
    # (same title, in its last weeks) but that isn't stitched would restart its total_gross.
    # The rest were first tracked after stat695's scrape and have nothing to continue.
    first_code = codes[0] if codes else None
    unlinked_carryovers, tracked_late = [], []
    if first_code:
        first_rows = main.filter((pl.col("code") == first_code) & (pl.col("style") == "new")
                                 & (pl.col("weeks") > 1))
        recent = legacy_last.filter(pl.col("last_weekend") >= boundary - timedelta(weeks=8))["title"].to_list()
        for r in first_rows.to_dicts():
            if r["key"] in links:
                continue
            item = {"bom_release_id": r["key"], "title": r["title"], "weeks": r["weeks"],
                    "total_gross": r["total_gross"]}
            if any(title_similarity(t, r["title"]) >= TITLE_MATCH for t in recent):
                unlinked_carryovers.append(item)
            else:
                tracked_late.append(item)

    statuses = Counter(r.status for r in results)
    report = {
        "source": SOURCE,
        "as_of": today.isoformat(),
        "boundary_weekend": boundary.isoformat(),
        "first_weekend": codes[0] if codes else None,
        "latest_weekend": codes[-1] if codes else None,
        "latest_weekend_end": sundays[-1].isoformat() if sundays else None,
        "weekends": len(codes),
        "statuses": dict(statuses),
        "archives": dict(Counter(r.archive for r in results if r.archive)),
        "styles": dict(Counter(r.style for r in results if r.style)),
        "snapshot_rows": snapshots.height,
        "unkeyed_rows": sum(r.page.unkeyed_rows for r in results if r.page),
        "releases_new": releases.height,
        "overlap_weekends": [weekend_code(s) for s in overlap_sundays],
        "overlap_statuses": dict(Counter(r.status for r in overlap_results)),
        "links": dict(Counter(lk.method for lk in links.values())),
        "link_conflicts": conflicts,
        "unlinked_carryovers": unlinked_carryovers,
        "carryovers_tracked_late": tracked_late,
        "estimate_rows": int(snapshots["is_estimate"].fill_null(False).sum()),
        "release_pages": {**page_stats, "with_tt": int(pages_df["tt_id"].is_not_null().sum()),
                          "eligible": len(order)},
        "network_requests": fetcher.network_requests,
        "minutes": round((time.monotonic() - started) / 60, 1),
        **stats,
    }
    return Ingest(snapshots, releases, links_df, overlap_results + results, pages_df, report)


WEEKEND_COLUMNS = ("code", "weekend_end", "status", "archive", "style", "capture_url", "rows",
                   "unkeyed_rows", "overlap", "notes")


def write_outputs(ing: Ingest, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ing.snapshots.write_parquet(out_dir / "bom_weekend_snapshots.parquet")
    ing.releases.write_parquet(out_dir / "bom_weekend_releases.parquet")
    ing.links.write_parquet(out_dir / "bom_weekend_links.parquet")
    ing.release_pages.write_parquet(out_dir / "bom_release_pages.parquet")
    overlap = set(ing.report["overlap_weekends"])
    with (out_dir / "bom_weekend_weekends.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(WEEKEND_COLUMNS)
        for r in ing.weekends:
            is_overlap = r.code in overlap  # stat695's weekends, re-read for stitching; never after it
            w.writerow([r.code, r.sunday.isoformat(), r.status, r.archive or "", r.style or "", r.capture_url or "",
                        len(r.page.rows) if r.page else 0, r.page.unkeyed_rows if r.page else 0,
                        "true" if is_overlap else "false", " | ".join(r.notes)])
    (out_dir / "bom_weekend_report.json").write_text(json.dumps(ing.report, indent=2, default=str) + "\n",
                                                    encoding="utf-8")


def run(fetcher: Fetcher | None = None, today: date | None = None) -> Ingest:
    """Build step: locate and fetch captures (CI only), parse, stitch, write to data/build/."""
    fetcher = fetcher or default_fetcher
    today = today or datetime.now(timezone.utc).date()
    legacy_snaps, legacy_releases = _legacy_inputs(paths.data_build())
    ing = ingest(
        fetcher, today, legacy_snaps, legacy_releases,
        minutes=_env_float(ENV_MINUTES, DEFAULT_MINUTES),
        release_page_lookups=int(_env_float(ENV_RELEASE_PAGES, DEFAULT_RELEASE_PAGES)),
        release_page_minutes=_env_float(ENV_RELEASE_MINUTES, DEFAULT_RELEASE_MINUTES),
    )
    write_outputs(ing, paths.data_build())
    r = ing.report
    print(f"  bom_weekend: {r['weekends']} weekends {r['first_weekend']} to {r['latest_weekend']} "
          f"{r['statuses']}, {r['snapshot_rows']} snapshots, {r['releases_new']} new releases, "
          f"links {r['links']}, {len(r['unlinked_carryovers'])} unlinked carry-overs, "
          f"{r['network_requests']} requests in {r['minutes']} min")
    return ing
