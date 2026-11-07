"""M3: identity matching. Every release gets a title_id: the IMDb ``tt`` id of
its Wikidata film item (P345), or a ``bb_`` id when there's no match.

Evidence, strongest first (``match_method`` on each release):

1. ``override``: ``data/manual/id_overrides.csv`` (by legacy id or rl id).
2. ``manual_group``: a ``tt`` title_id set in ``data/manual/title_groups.csv``.
3. ``release_page``: the ``tt`` id on the release's archived Box Office Mojo
   release page, found on Wikidata by P345.
4. ``p1237``: a Wikidata item whose legacy Box Office Mojo film ID (P1237)
   is the release's legacy id.
5. ``group``: releases M1/M2 grouped into one provisional title (re-release
   detection, shared release-page titles) follow a matched member.
6. ``title_year`` / ``fuzzy``: the title of the group's original release
   equals (or, with rapidfuzz ratio >= 90 and the same numbers, nearly
   equals) a Wikidata film's English label or alias, published within a year.
   Date proximity and sitelinks break ties; a near tie stays unmatched. Films
   already claimed by another original release are skipped.
7. ``rerelease_title`` / ``rerelease_wikidata``: a re-release with no matched
   original in its group takes the one earlier matched release of the same
   title, else the one earlier Wikidata film of that title.

Items without P345 give ``bb_<qid>`` ids. Unmatched releases keep their
provisional ``bb_`` id and still appear on the site.

Writes ``data/build/match.parquet``, ``match_report.csv`` (every release,
with its score and best candidates) and ``match_report.json`` (coverage, the
accept criteria, conflicts), and builds ``titles.parquet``.
"""

from __future__ import annotations

import csv
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import polars as pl
from rapidfuzz import fuzz, process

from . import paths
from .manual import TT_RE, load_manual
from .sources.stat695 import split_title
from .sources.wikidata import norm_bom_id

RL_RE = re.compile(r"^rl\d+$")
YEAR_SUFFIX_RE = re.compile(r"\s*\((?P<year>(?:19|20)\d{2})\)\s*$")

FUZZY_MIN = 90  # rapidfuzz ratio on normalized titles
MARGIN = 2.0  # the best candidate must beat the next by this much
YEAR_PENALTY = 3.0  # per year between the release and the film's nearest publication date
DATE_WINDOW = timedelta(days=10)
US_DATE_BONUS, DATE_BONUS = 4.0, 3.0  # a US (or any) publication date this close to the release
SITELINK_BONUS = 1.5  # times log10(1 + sitelinks), capped
SITELINK_BONUS_MAX = 3.0
RERELEASE_SITELINK_RATIO = 3  # an unclaimed re-release candidate must be this much better known
US = "Q30"
CANDIDATES_KEPT = 3
TOP_RELEASES = 1000
MATCHED_GROSS_TARGET = 0.97
LISTED = 50  # entries kept per report list

METHODS = {
    "override": "data/manual/id_overrides.csv",
    "manual_group": "a tt title_id in data/manual/title_groups.csv",
    "release_page": "the IMDb id linked from the archived release page, found on Wikidata by P345",
    "p1237": "the Wikidata item whose legacy Box Office Mojo id (P1237) is the release's",
    "group": "grouped by M1/M2 with a matched release",
    "title_year": "same title as a Wikidata film published within a year",
    "fuzzy": f"near-identical title (ratio >= {FUZZY_MIN}) of a Wikidata film published within a year",
    "rerelease_title": "a re-release titled like one earlier matched release",
    "rerelease_wikidata": "a re-release titled like one earlier Wikidata film",
    "unmatched": "no match: keeps its provisional bb_ title_id",
}

TITLE_SCHEMA = {
    "title_id": pl.String, "wikidata_qid": pl.String, "title": pl.String, "year": pl.Int32,
    "release_date": pl.Date, "distributor": pl.String, "genres": pl.String, "mpaa": pl.String,
    "pre1982_baseline_gross": pl.Float64, "baseline_is_rental": pl.Boolean, "baseline_source": pl.String,
}
MATCH_SCHEMA = {
    "release_id": pl.String, "title_id": pl.String, "wikidata_qid": pl.String, "match_method": pl.String,
    "score": pl.Float64, "detail": pl.String,
}


# --- titles ----------------------------------------------------------------

_ROMAN = {"ii": 2, "iii": 3, "iv": 4, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "xi": 11, "xii": 12}


def norm(title: str | None) -> str:
    """Comparable title: no accents, case, punctuation or leading article."""
    t = unicodedata.normalize("NFKD", title or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower().replace("&", " and ")
    t = re.sub(r"['’`.]", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return re.sub(r"^(the|a|an) ", "", t)


def numbers(normed: str) -> tuple[int, ...]:
    """The numbers in a normalized title, Roman numerals too: sequels must agree on them."""
    return tuple(sorted(int(w) if w.isdigit() else _ROMAN[w] for w in normed.split()
                        if w.isdigit() or w in _ROMAN))


def base_title(title: str | None) -> tuple[str, int | None]:
    """(normalized title without re-release wording or a "(2016)" tag, that tag's year)."""
    base = split_title(title or "")[0]
    m = YEAR_SUFFIX_RE.search(base)
    year = int(m["year"]) if m else None
    return norm(YEAR_SUFFIX_RE.sub("", base)), year


# --- Wikidata films ----------------------------------------------------------

@dataclass
class Film:
    qid: str
    tt: str | None
    label: str | None
    names: list[str]  # normalized label and aliases
    sitelinks: int
    years: list[int]
    dates: list[tuple[date, str | None]]  # day-precision dates, with place
    bom_ids: list[str]

    @property
    def title_id(self) -> str:
        return self.tt or f"bb_{self.qid.lower()}"

    @property
    def us_date(self) -> date | None:
        return min((d for d, place in self.dates if place == US), default=None)


class FilmIndex:
    def __init__(self, films: list[Film]) -> None:
        self.by_qid = {f.qid: f for f in films}
        self.by_tt: dict[str, list[str]] = defaultdict(list)
        self.by_bom: dict[str, list[str]] = defaultdict(list)
        self.by_norm: dict[str, list[str]] = defaultdict(list)
        self.by_year: dict[int, list[tuple[str, str]]] = defaultdict(list)
        for f in films:
            for b in f.bom_ids:
                self.by_bom[b].append(f.qid)
            for n in f.names:
                self.by_norm[n].append(f.qid)
            for y in f.years:
                self.by_year[y].extend((n, f.qid) for n in f.names)
        self._windows: dict[tuple[int, int], tuple[list[str], list[str]]] = {}

    def add_tts(self, rows: list[tuple[str, list[str]]]) -> None:
        for qid, tts in rows:
            for t in tts:
                self.by_tt[t].append(qid)

    def __len__(self) -> int:
        return len(self.by_qid)

    def pick(self, qids: list[str]) -> str | None:
        """Of several items, the one with an IMDb id, then the best known, then the oldest."""
        if not qids:
            return None
        return min(set(qids), key=lambda q: (self.by_qid[q].tt is None, -self.by_qid[q].sitelinks,
                                             int(q[1:])))

    def window(self, y0: int, y1: int) -> tuple[list[str], list[str]]:
        """Names and qids of films published in [y0, y1]."""
        key = (y0, y1)
        if key not in self._windows:
            pairs = sorted({p for y in range(y0, y1 + 1) for p in self.by_year.get(y, [])})
            self._windows[key] = ([p[0] for p in pairs], [p[1] for p in pairs])
        return self._windows[key]


def load_films(path: Path) -> FilmIndex:
    if not path.is_file():
        return FilmIndex([])
    df = pl.read_parquet(path)
    films, tts = [], []
    for r in df.iter_rows(named=True):
        names = []
        for n in [r["label"], *(r["aliases"] or [])]:
            k = norm(n)
            if k and k not in names:
                names.append(k)
        dates = r["dates"] or []
        films.append(Film(
            qid=r["qid"], tt=r["tt"], label=r["label"], names=names, sitelinks=r["sitelinks"] or 0,
            years=sorted({d["year"] for d in dates if d["year"] is not None}),
            dates=[(d["date"], d["place"]) for d in dates if d["date"] is not None],
            bom_ids=list(r["bom_ids"] or []),
        ))
        tts.append((r["qid"], list(r["tts"] or [])))
    index = FilmIndex(films)
    index.add_tts(tts)
    return index


# --- matching ------------------------------------------------------------------

@dataclass
class Assign:
    title_id: str
    qid: str | None
    method: str
    score: float | None = None
    detail: str = ""


@dataclass
class Candidate:
    qid: str
    sim: float
    composite: float
    year_gap: int

    def describe(self, films: FilmIndex) -> str:
        f = films.by_qid[self.qid]
        year = f.years[0] if f.years else "?"
        return f"{self.qid} {f.label!r} ({year}) {self.sim:.0f}/{self.composite:.1f}"


@dataclass
class Outcome:
    assign: Assign | None
    candidates: list[Candidate] = field(default_factory=list)
    why: str = ""


def _release_year_hints(r: dict) -> set[int]:
    years = {r["first_weekend"].year} if r.get("first_weekend") else set()
    if r.get("release_date"):
        years.add(r["release_date"].year)
    tagged = base_title(r.get("title"))[1]
    if tagged:
        years.add(tagged)
    return years


def _bonus(film: Film, r: dict) -> float:
    targets = [d for d in (r.get("release_date"),
                           r["first_weekend"] - timedelta(days=2) if r.get("first_weekend") else None) if d]
    bonus = 0.0
    for d, place in film.dates:
        if any(abs(d - t) <= DATE_WINDOW for t in targets):
            bonus = max(bonus, US_DATE_BONUS if place == US else DATE_BONUS)
    return bonus + min(SITELINK_BONUS_MAX, SITELINK_BONUS * math.log10(1 + film.sitelinks))


def match_original(r: dict, films: FilmIndex, excluded) -> Outcome:
    """Title + publication year against Wikidata films, for an original (not re-) release."""
    query, _ = base_title(r.get("title"))
    years = _release_year_hints(r)
    if not query or not years:
        return Outcome(None, why="no title or year")
    names, qids = films.window(min(years) - 1, max(years) + 1)
    if not names:
        return Outcome(None, why="no Wikidata films in those years")
    want = numbers(query)
    best: dict[str, float] = {}
    for name, sim, i in process.extract(query, names, scorer=fuzz.ratio, score_cutoff=FUZZY_MIN, limit=50):
        sim = 100.0 if name == query else float(sim)
        if sim < 100 and numbers(name) != want:
            continue
        q = qids[i]
        best[q] = max(best.get(q, 0.0), sim)
    cands, skipped = [], []
    for q, sim in best.items():
        if excluded(q):
            skipped.append(q)
            continue
        f = films.by_qid[q]
        gap = min((abs(fy - y) for fy in f.years for y in years), default=9)
        cands.append(Candidate(q, sim, sim - YEAR_PENALTY * gap + _bonus(f, r), gap))
    cands.sort(key=lambda c: (-c.composite, c.qid))
    if not cands:
        why = f"only films claimed by other releases ({', '.join(sorted(skipped)[:3])})" if skipped else "no close title"
        return Outcome(None, why=why)
    top = cands[0]
    if len(cands) > 1 and cands[1].composite > top.composite - MARGIN:
        return Outcome(None, cands[:CANDIDATES_KEPT], "ambiguous")
    method = "title_year" if top.sim == 100 else "fuzzy"
    f = films.by_qid[top.qid]
    return Outcome(Assign(f.title_id, f.qid, method, round(top.composite, 1)), cands[:CANDIDATES_KEPT])


def match_rerelease_wikidata(r: dict, films: FilmIndex, claimed: dict[str, set]) -> Outcome:
    """A re-release of a film first published before it, by exact title."""
    query, _ = base_title(r.get("title"))
    first = r["first_weekend"].year if r.get("first_weekend") else None
    if not query or first is None:
        return Outcome(None, why="no title or year")
    pool = [films.by_qid[q] for q in set(films.by_norm.get(query, []))]
    pool = [f for f in pool if f.years and f.years[0] < first]
    pool.sort(key=lambda f: (-f.sitelinks, f.qid))
    cands = [Candidate(f.qid, 100.0, float(f.sitelinks), 0) for f in pool]
    in_data = [f for f in pool if claimed.get(f.qid)]
    chosen = None
    if len(in_data) == 1:
        chosen = in_data[0]
    elif not in_data and len(pool) == 1:
        chosen = pool[0]
    elif not in_data and len(pool) > 1 and pool[0].sitelinks >= RERELEASE_SITELINK_RATIO * max(1, pool[1].sitelinks):
        chosen = pool[0]
    if chosen is None:
        return Outcome(None, cands[:CANDIDATES_KEPT], "ambiguous" if pool else "no earlier film of that title")
    return Outcome(Assign(chosen.title_id, chosen.qid, "rerelease_wikidata", float(chosen.sitelinks)),
                   cands[:CANDIDATES_KEPT])


def _root(members: list[dict]) -> dict:
    originals = [m for m in members if not m.get("is_rerelease")]
    return min(originals or members, key=lambda m: (m.get("first_weekend") or date.max, m["release_id"]))


@dataclass
class MatchResult:
    assign: dict[str, Assign]
    outcomes: dict[str, Outcome]  # by group root release_id, for groups that went to title matching
    notes: dict[str, list[str]]


def match_releases(rels: list[dict], films: FilmIndex, pages: dict[str, str],
                   overrides: dict[str, dict]) -> MatchResult:
    """``rels`` need release_id, title_id (provisional), source_key, bom_release_id, title,
    release_date, first_weekend, is_rerelease, group_source and gross."""
    assign: dict[str, Assign] = {}
    notes: dict[str, list[str]] = defaultdict(list)

    # 1. Direct evidence, release by release.
    for r in rels:
        rid, key, rl = r["release_id"], r.get("source_key") or "", r.get("bom_release_id")
        ov = next((overrides[k] for k in (key, rl) if k and k in overrides), None)
        if ov is not None:
            tid = ov["title_id"]
            qid = ov.get("wikidata_qid") or (films.pick(films.by_tt.get(tid, [])) if TT_RE.match(tid) else None)
            assign[rid] = Assign(tid, qid, "override", detail=(ov.get("source") or "")[:120])
            continue
        if r.get("group_source") == "manual" and TT_RE.match(r.get("title_id") or ""):
            tid = r["title_id"]
            assign[rid] = Assign(tid, films.pick(films.by_tt.get(tid, [])), "manual_group")
            continue
        via_page = via_bom = None
        if rl and rl in pages:
            tt = pages[rl]
            q = films.pick(films.by_tt.get(tt, []))
            if q:
                via_page = Assign(films.by_qid[q].title_id, q, "release_page", detail=f"{rl} -> {tt}")
            else:
                notes["release_page_tt_not_on_wikidata"].append(f"{rid} {r.get('title')!r}: {rl} -> {tt}")
        legacy = None if RL_RE.match(key) else key
        if legacy:
            qs = films.by_bom.get(norm_bom_id(legacy), [])
            if len(set(qs)) > 1:
                notes["p1237_on_several_items"].append(f"{legacy}: {', '.join(sorted(set(qs)))}")
            q = films.pick(qs)
            if q:
                via_bom = Assign(films.by_qid[q].title_id, q, "p1237", detail=legacy)
        if via_page and via_bom and via_page.title_id != via_bom.title_id:
            notes["release_page_vs_p1237"].append(
                f"{rid} {r.get('title')!r}: page {via_page.title_id} ({via_page.qid}), "
                f"P1237 {via_bom.title_id} ({via_bom.qid}); the page wins")
        if via_page or via_bom:
            assign[rid] = via_page or via_bom

    # 2. Provisional groups follow their matched members.
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rels:
        groups[r["title_id"]].append(r)

    def propagate(members: list[dict]) -> None:
        direct = [(m, assign[m["release_id"]]) for m in members if m["release_id"] in assign]
        if not direct or len(direct) == len(members):
            if direct and len({a.title_id for _, a in direct}) > 1:
                notes["group_conflicts"].append(_conflict(members, direct))
            return
        tids = {a.title_id for _, a in direct}
        root = _root(members)
        if len(tids) == 1:
            source, chosen = direct[0]
        else:
            notes["group_conflicts"].append(_conflict(members, direct))
            source, chosen = next(((m, a) for m, a in direct if m is root),
                                  max(direct, key=lambda ma: ma[0].get("gross") or 0))
        for m in members:
            if m["release_id"] not in assign:
                assign[m["release_id"]] = Assign(chosen.title_id, chosen.qid, "group",
                                                 detail=f"with {source['release_id']}")

    for members in groups.values():
        propagate(members)

    claimed: dict[str, set] = defaultdict(set)  # qid -> groups with an original release matched to it
    for g, members in groups.items():
        for m in members:
            a = assign.get(m["release_id"])
            if a and a.qid and not m.get("is_rerelease"):
                claimed[a.qid].add(g)

    def gross_of(members: list[dict]) -> int:
        return sum(m.get("gross") or 0 for m in members)

    pending = sorted((g for g, ms in groups.items() if not any(m["release_id"] in assign for m in ms)),
                     key=lambda g: (-gross_of(groups[g]), g))
    outcomes: dict[str, Outcome] = {}

    def settle(g: str, outcome: Outcome) -> None:
        root = _root(groups[g])
        outcomes[root["release_id"]] = outcome
        a = outcome.assign
        if a is None:
            return
        for m in groups[g]:
            assign[m["release_id"]] = Assign(a.title_id, a.qid, a.method, a.score,
                                             a.detail or (f"via {root['release_id']}" if m is not root else ""))
        if a.qid and any(not m.get("is_rerelease") for m in groups[g]):
            claimed[a.qid].add(g)

    # 3. Original releases by title and year, biggest first.
    for g in pending:
        root = _root(groups[g])
        if root.get("is_rerelease"):
            continue
        settle(g, match_original(root, films, lambda q, g=g: bool(claimed.get(q, set()) - {g})))

    # 4. Re-releases whose originals aren't in their group.
    originals_by_title: dict[str, set[tuple[str, str | None, date]]] = defaultdict(set)
    for r in rels:
        a = assign.get(r["release_id"])
        if a and not r.get("is_rerelease") and r.get("first_weekend"):
            originals_by_title[base_title(r.get("title"))[0]].add((a.title_id, a.qid, r["first_weekend"]))
    for g in pending:
        root = _root(groups[g])
        if not root.get("is_rerelease") or root["release_id"] in assign:
            continue
        base = base_title(root.get("title"))[0]
        earlier = {(t, q) for t, q, fw in originals_by_title.get(base, ()) if fw < root["first_weekend"]}
        if len(earlier) == 1:
            t, q = earlier.pop()
            settle(g, Outcome(Assign(t, q, "rerelease_title")))
        elif len(earlier) > 1:
            settle(g, Outcome(None, why="several earlier releases of that title: "
                              + ", ".join(sorted(t for t, _ in earlier))[:200]))
        else:
            settle(g, match_rerelease_wikidata(root, films, claimed))

    # Unmatched releases keep their provisional ids.
    for r in rels:
        if r["release_id"] not in assign:
            assign[r["release_id"]] = Assign(r["title_id"], None, "unmatched")
    return MatchResult(assign, outcomes, dict(notes))


def _conflict(members: list[dict], direct: list[tuple[dict, Assign]]) -> str:
    parts = "; ".join(f"{m['release_id']} -> {a.title_id} ({a.method})" for m, a in direct)
    return f"group {members[0]['title_id']}: {parts}"


# --- applying it -------------------------------------------------------------------

@dataclass
class Applied:
    releases: pl.DataFrame
    snapshots: pl.DataFrame
    titles: pl.DataFrame
    report: dict


def release_pages(build_dir: Path) -> dict[str, str]:
    p = build_dir / "bom_release_pages.parquet"
    if not p.is_file():
        return {}
    df = pl.read_parquet(p).filter(pl.col("tt_id").is_not_null())
    return {rl: tt for rl, tt in zip(df["rl_id"].to_list(), df["tt_id"].to_list()) if TT_RE.match(tt)}


def _apply_label_overrides(releases: pl.DataFrame, overrides: dict[str, dict]) -> pl.DataFrame:
    """An override's release_label marks the release as a re-release with that label."""
    labelled = {k: o["release_label"] for k, o in overrides.items() if o.get("release_label")}
    if not labelled:
        return releases
    rows = releases.to_dicts()
    for r in rows:
        label = labelled.get(r["source_key"]) or labelled.get(r.get("bom_release_id") or "")
        if label:
            r.update(label=label, is_rerelease=True, rerelease_reason="manual", group_source="manual")
    return pl.DataFrame(rows, schema=releases.schema)


def build_titles(rels: list[dict], assign: dict[str, Assign], films: FilmIndex,
                 baseline: list[dict]) -> pl.DataFrame:
    """One row per title_id: the original release's facts, or Wikidata's for re-release-only titles."""
    by_title: dict[str, list[dict]] = defaultdict(list)
    for r in rels:
        by_title[r["title_id"]].append(r)
    base_rows: dict[str, dict] = {}
    for b in baseline:
        tid = b.get("title_id")
        if not tid and b.get("wikidata_qid") in films.by_qid:
            tid = films.by_qid[b["wikidata_qid"]].title_id
        if tid:
            base_rows[tid] = b
    out = []
    for tid in sorted(set(by_title) | set(base_rows)):
        members = by_title.get(tid, [])
        b = base_rows.get(tid)
        qids = Counter(assign[m["release_id"]].qid for m in members if assign[m["release_id"]].qid)
        qid = qids.most_common(1)[0][0] if qids else (b.get("wikidata_qid") if b else None)
        film = films.by_qid.get(qid) if qid else None
        row = {"title_id": tid, "wikidata_qid": qid}
        if members:
            originals = [m for m in members if not m.get("is_rerelease")]
            root = _root(members)
            us = film.us_date if film else None
            if originals:
                title = root["title"]
                rd = root.get("release_date")
                if rd is None and us and root.get("first_weekend") and abs(us - root["first_weekend"]) <= timedelta(days=365):
                    rd = us
                year = rd.year if rd else root["first_weekend"].year
            else:
                title = (film.label if film and film.label else None) or split_title(root["title"] or "")[0]
                rd = us
                year = rd.year if rd else (film.years[0] if film and film.years else None)
            row.update(title=title, year=year, release_date=rd, distributor=root.get("distributor"),
                       genres=root.get("genres"), mpaa=root.get("mpaa"))
        else:
            row.update(title=b["title"], year=b["release_year"])
        if b:
            src = b["source"] + (f" ({b['source_url']})" if b.get("source_url") else "")
            row.update(pre1982_baseline_gross=b["gross_usd"], baseline_is_rental=b["is_rental"], baseline_source=src)
        out.append(row)
    return pl.DataFrame(out, schema=TITLE_SCHEMA)


def _report(rels: list[dict], result: MatchResult, films_loaded: int, wikidata_report: dict | None) -> dict:
    assign = result.assign
    total = sum(r.get("gross") or 0 for r in rels)
    by_method: dict[str, dict] = {}
    for r in rels:
        a = assign[r["release_id"]]
        m = by_method.setdefault(a.method, {"releases": 0, "gross": 0})
        m["releases"] += 1
        m["gross"] += r.get("gross") or 0
    for m in by_method.values():
        m["share"] = round(m["gross"] / total, 4) if total else 0.0
    matched = sum(r.get("gross") or 0 for r in rels if TT_RE.match(assign[r["release_id"]].title_id))
    top = sorted(rels, key=lambda r: (-(r.get("gross") or 0), r["release_id"]))[:TOP_RELEASES]
    top_unmatched = [{"release_id": r["release_id"], "title": r.get("title"), "gross": r.get("gross"),
                      "method": assign[r["release_id"]].method, "title_id": assign[r["release_id"]].title_id}
                     for r in top if not TT_RE.match(assign[r["release_id"]].title_id)]
    by_rid = {r["release_id"]: r for r in rels}
    ambiguous = sorted(((by_rid[rid].get("gross") or 0, rid, o) for rid, o in result.outcomes.items()
                        if o.assign is None and o.why == "ambiguous"), key=lambda x: (-x[0], x[1]))
    return {
        "films_loaded": films_loaded,
        "wikidata_snapshot": (wikidata_report or {}).get("snapshot"),
        "wikidata_stale": bool((wikidata_report or {}).get("stale_reason")),
        "releases": len(rels),
        "titles": len({a.title_id for a in assign.values()}),
        "gross_total": total,
        "gross_matched_tt": matched,
        "matched_share": round(matched / total, 4) if total else 0.0,
        "matched_target": MATCHED_GROSS_TARGET,
        "top_releases": TOP_RELEASES,
        "top_unmatched": top_unmatched,
        "by_method": dict(sorted(by_method.items(), key=lambda kv: list(METHODS).index(kv[0]))),
        "ambiguous_count": len(ambiguous),
        "ambiguous": [{"release_id": rid, "title": by_rid[rid].get("title"), "gross": g,
                       "candidates": [c.qid for c in o.candidates]} for g, rid, o in ambiguous[:LISTED]],
        "notes": {k: {"count": len(v), "examples": v[:LISTED]} for k, v in sorted(result.notes.items())},
    }


def _write_csv(path: Path, rels: list[dict], result: MatchResult, films: FilmIndex) -> None:
    roots: dict[str, Outcome] = result.outcomes
    root_of_title: dict[str, str] = {}
    for r in rels:
        if r["release_id"] in roots:
            root_of_title[r["title_id"]] = r["release_id"]
    cols = ("release_id", "source_key", "bom_release_id", "title", "label", "first_weekend", "release_date",
            "gross", "match_method", "title_id", "wikidata_qid", "wikidata_label", "score", "detail", "why",
            "candidates")
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in sorted(rels, key=lambda x: (-(x.get("gross") or 0), x["release_id"])):
            a = result.assign[r["release_id"]]
            o = roots.get(r["release_id"]) or roots.get(root_of_title.get(r["title_id"], ""))
            f = films.by_qid.get(a.qid) if a.qid else None
            w.writerow([
                r["release_id"], r.get("source_key") or "", r.get("bom_release_id") or "", r.get("title") or "",
                r.get("label") or "", r.get("first_weekend") or "", r.get("release_date") or "", r.get("gross") or 0,
                a.method, a.title_id, a.qid or "", (f.label if f else "") or "",
                "" if a.score is None else a.score, a.detail, o.why if o else "",
                " | ".join(c.describe(films) for c in o.candidates) if o else "",
            ])


def apply(releases: pl.DataFrame, snapshots: pl.DataFrame, build_dir: Path | None = None,
          manual_dir: Path | None = None, log=print) -> Applied:
    """Match releases, rewrite title_ids in releases and snapshots, build titles, write reports."""
    build_dir = build_dir or paths.data_build()
    films = load_films(build_dir / "wikidata_films.parquet")
    wd_report_path = build_dir / "wikidata_report.json"
    wd_report = json.loads(wd_report_path.read_text(encoding="utf-8")) if wd_report_path.is_file() else None
    overrides = {o["source_key"]: o for o in load_manual("id_overrides.csv", manual_dir)}
    baseline = load_manual("pre1982_baseline.csv", manual_dir)
    releases = _apply_label_overrides(releases, overrides)

    gross = snapshots.group_by("release_id").agg(pl.col("total_gross").max().alias("gross"))
    rels = releases.join(gross, on="release_id", how="left").to_dicts()
    result = match_releases(rels, films, release_pages(build_dir), overrides)
    a = result.assign

    out_releases = releases.with_columns(
        pl.col("release_id").replace_strict({k: v.title_id for k, v in a.items()}, return_dtype=pl.String)
        .alias("title_id"),
        pl.col("release_id").replace_strict({k: v.method for k, v in a.items()}, return_dtype=pl.String)
        .alias("match_method"),
    )
    out_snapshots = snapshots.with_columns(
        pl.col("release_id").replace_strict({k: v.title_id for k, v in a.items()}, default=None,
                                            return_dtype=pl.String).alias("title_id"))
    final = out_releases.join(gross, on="release_id", how="left").to_dicts()
    titles = build_titles(final, a, films, baseline)

    report = _report(rels, result, len(films), wd_report)
    build_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame([{"release_id": k, "title_id": v.title_id, "wikidata_qid": v.qid, "match_method": v.method,
                   "score": v.score, "detail": v.detail} for k, v in sorted(a.items())],
                 schema=MATCH_SCHEMA).write_parquet(build_dir / "match.parquet")
    _write_csv(build_dir / "match_report.csv", rels, result, films)
    (build_dir / "match_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    methods = ", ".join(f"{k} {v['releases']} ({v['share']:.1%})" for k, v in report["by_method"].items())
    log(f"  match: {report['releases']} releases -> {report['titles']} titles; {report['matched_share']:.2%} of "
        f"gross matched to an IMDb id (target {MATCHED_GROSS_TARGET:.0%}); "
        f"{len(report['top_unmatched'])} of the top {TOP_RELEASES} releases unmatched; {methods}")
    for t in report["top_unmatched"][:20]:
        log(f"  match: top release unmatched: {t['release_id']} {t['title']!r} ${t['gross'] or 0:,}")
    return Applied(out_releases, out_snapshots, titles, report)
