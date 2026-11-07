"""Parsers for archived Box Office Mojo pages (M2).

* New-style weekend chart (``/weekend/2020W01/``, the site since Oct 2019):
  one ``mojo-body-table``. Columns are found by their header ``title``
  attributes ("Weekend Gross", "Total Gross", ...), not by position. Each
  film links to ``/release/rl…/``; re-releases carry a grey sub-label such as
  "2019 re-release". Two hidden boolean columns mark films new that weekend
  and figures that are still estimates.
* Old-style weekend chart (``/weekend/chart/?yr=2017&wknd=05&p=.htm``, before
  Oct 2019): nested layout tables. Films link to ``/movies/?id=<legacy id>.htm``,
  the same legacy ids stat695data uses.
* Release page (``/release/rl…/``): the IMDb ``tt`` id it links to (for M3
  matching through Wikidata P345), release date, MPAA rating and genres.

Tests use hand-written synthetic HTML that mimics these structures, never
saved copies of real pages.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser

from .. import htmltables
from ..htmltables import Cell, squash


class NotAChart(ValueError):
    """The page isn't the expected Box Office Mojo chart (an error or robot-check page, say)."""


@dataclass
class ChartRow:
    rank: int | None
    title: str
    label: str | None
    key: str | None  # rl id (new style) or legacy movie id (old style); None if the row has no link
    weekend_gross: int | None
    theaters: int | None
    total_gross: int | None
    weeks: int | None
    distributor: str | None
    is_new: bool | None
    is_estimate: bool | None


@dataclass
class ChartPage:
    style: str  # "new" | "old"
    year: int | None  # from the page heading (new style only)
    week: int | None
    start: date | None
    end: date | None
    rows: list[ChartRow] = field(default_factory=list)
    unkeyed_rows: int = 0


# --- values -------------------------------------------------------------------

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTHS["sept"] = 9
_RANGE_RE = re.compile(
    r"(?P<m1>[A-Za-z]{3,9})\.?\s+(?P<d1>\d{1,2})(?:,\s*(?P<y1>\d{4}))?\s*[-–—]\s*"
    r"(?:(?P<m2>[A-Za-z]{3,9})\.?\s+)?(?P<d2>\d{1,2}),?\s+(?P<y2>\d{4})"
)
_NUMBER_RE = re.compile(r"^[+-]?\$?[\d,]+$")


def parse_date_range(text: str) -> tuple[date, date] | None:
    """'January 3-5, 2020', 'January 31-February 2, 2020', 'December 31, 2021-January 2, 2022'."""
    for m in _RANGE_RE.finditer(text):
        m1 = _MONTHS.get(m["m1"].lower())
        m2 = _MONTHS.get(m["m2"].lower()) if m["m2"] else m1
        if m1 is None or m2 is None:
            continue
        y2 = int(m["y2"])
        y1 = int(m["y1"]) if m["y1"] else (y2 if m1 <= m2 else y2 - 1)
        try:
            return date(y1, m1, int(m["d1"])), date(y2, m2, int(m["d2"]))
        except ValueError:
            continue
    return None


def parse_int(text: str | None) -> int | None:
    """'$34,524,815' -> 34524815; '4,406' -> 4406; '-', 'n/a' or '' -> None."""
    t = (text or "").strip()
    if not _NUMBER_RE.match(t):
        return None
    t = t.replace("$", "").replace(",", "").replace("+", "")
    return int(t) if t not in ("", "-") else None


def _text_or_none(text: str | None) -> str | None:
    t = squash(text or "")
    return None if t in ("", "-", "n/a", "N/A") else t


def _bool(text: str | None) -> bool | None:
    t = (text or "").strip().lower()
    return True if t == "true" else False if t == "false" else None


def _label(cell: Cell) -> str:
    return cell.titles[0] if cell.titles else cell.text


# --- new-style weekend chart ----------------------------------------------------

NEW_COLUMNS: dict[str, tuple[str, ...]] = {
    "rank": ("Rank",),
    "release": ("Release",),
    "weekend_gross": ("Weekend Gross", "Gross"),
    "theaters": ("Number of Theaters", "Theaters"),
    "total_gross": ("Total Gross",),
    "weeks": ("Number of Weeks In Release", "Weeks"),
    "distributor": ("Distributor",),
    "is_new": ("Is New This Week", "New This Week"),
    "is_estimate": ("Estimated",),
}
NEW_REQUIRED = ("rank", "release", "weekend_gross", "total_gross")
_RL_RE = re.compile(r"/release/(rl\d+)")
_H1_RE = re.compile(r"(?P<area>.*?)\s*(?P<year>\d{4})\s+Weekend\s+(?P<week>\d{1,2})\b", re.I)


def _column_map(header: list[Cell], wanted: dict[str, tuple[str, ...]]) -> dict[str, int]:
    labels = [_label(c) for c in header]
    texts = [c.text for c in header]
    out: dict[str, int] = {}
    for key, names in wanted.items():
        for name in names:
            idx = next((i for i, lab in enumerate(labels) if lab == name), None)
            if idx is None:
                idx = next((i for i, t in enumerate(texts) if t == name), None)
            if idx is not None and idx not in out.values():
                out[key] = idx
                break
    return out


def parse_new_weekend(html: str) -> ChartPage:
    page = htmltables.parse(html)
    heading = next((t for tag, t in page.headings if tag == "h1" and _H1_RE.search(t)), None)
    if heading is None:
        raise NotAChart("no 'YYYY Weekend N' heading")
    h1 = _H1_RE.search(heading)
    if "domestic" not in h1["area"].lower():
        raise NotAChart(f"not the domestic chart: {heading!r}")
    span = next((r for _, t in page.headings if (r := parse_date_range(t))), None)

    for table in page.tables:
        header_row = next((r for r in table.rows if r.cells and all(c.tag == "th" for c in r.cells)), None)
        if header_row is None:
            continue
        cols = _column_map(header_row.cells, NEW_COLUMNS)
        if all(k in cols for k in NEW_REQUIRED):
            break
    else:
        raise NotAChart("no weekend chart table")

    out = ChartPage("new", int(h1["year"]), int(h1["week"]), span[0] if span else None, span[1] if span else None)

    def cell(r, key):
        i = cols.get(key)
        return r.cells[i] if i is not None and i < len(r.cells) else None

    for row in table.rows:
        if row is header_row or not row.cells or all(c.tag == "th" for c in row.cells):
            continue
        if any(cell(row, k) is None for k in NEW_REQUIRED):
            continue  # not a film row (too few cells)
        rel = cell(row, "release")
        rl = next((m[1] for href, _ in rel.links if (m := _RL_RE.search(href))), None)
        title = next((t for href, t in rel.links if _RL_RE.search(href) and t), None)
        label = _text_or_none(rel.secondary)
        if title is None:
            title = squash(rel.text.replace(rel.secondary, "", 1)) if rel.secondary else rel.text
        if rl is None:
            out.unkeyed_rows += 1
            continue
        est = _bool(cell(row, "is_estimate").text) if cell(row, "is_estimate") else None
        if est is None and "mojo-annotation-isEstimated" in row.classes:
            est = True
        new = _bool(cell(row, "is_new").text) if cell(row, "is_new") else None
        if new is None and "mojo-annotation-isNewThisWeek" in row.classes:
            new = True
        out.rows.append(ChartRow(
            rank=parse_int(cell(row, "rank").text),
            title=title,
            label=label,
            key=rl,
            weekend_gross=parse_int(cell(row, "weekend_gross").text),
            theaters=parse_int(cell(row, "theaters").text) if cell(row, "theaters") else None,
            total_gross=parse_int(cell(row, "total_gross").text),
            weeks=parse_int(cell(row, "weeks").text) if cell(row, "weeks") else None,
            distributor=_text_or_none(cell(row, "distributor").text) if cell(row, "distributor") else None,
            is_new=new,
            is_estimate=est,
        ))
    return out


# --- old-style weekend chart ----------------------------------------------------

OLD_COLUMNS: dict[str, tuple[str, ...]] = {
    "rank": ("TW",),
    "lw": ("LW",),
    "title": ("Title (click to view)", "Title"),
    "distributor": ("Studio",),
    "weekend_gross": ("Weekend Gross",),
    "theaters": ("Theater Count / Change", "Theater Count", "Theaters"),
    "total_gross": ("Total Gross", "Gross-to-Date"),
    "weeks": ("Week #", "Weeks"),
}
OLD_REQUIRED = ("rank", "title", "weekend_gross", "total_gross")
_LEGACY_RE = re.compile(r"/movies/\?(?:[^\"'#]*&(?:amp;)?)?id=([^&\"'#]+?)\.html?\b", re.I)


def _expand(header: list[Cell]) -> list[Cell]:
    """Header cells repeated over their colspans, so data cells line up by index."""
    out: list[Cell] = []
    for c in header:
        out.extend([c] * c.colspan)
    return out


def parse_old_weekend(html: str) -> ChartPage:
    page = htmltables.parse(html)
    span = parse_date_range(page.title)
    if span is None or "weekend" not in page.title.lower():
        raise NotAChart(f"not an old-style weekend chart: {page.title!r}")
    estimates = "estimate" in page.title.lower()

    for table in page.tables:
        for i, row in enumerate(table.rows):
            texts = [c.text for c in row.cells]
            if "TW" in texts and any(t.startswith("Title") for t in texts):
                expanded = _expand(row.cells)
                firsts: dict[str, int] = {}
                for key, names in OLD_COLUMNS.items():
                    for j, c in enumerate(expanded):
                        if c.text in names and key not in firsts:
                            firsts[key] = j
                if all(k in firsts for k in OLD_REQUIRED):
                    header_index, cols = i, firsts
                    break
        else:
            continue
        break
    else:
        raise NotAChart("no chart header row (TW, LW, Title...)")

    out = ChartPage("old", None, None, span[0], span[1])
    for row in table.rows[header_index + 1:]:
        cells = row.cells
        if len(cells) <= max(cols.values()):
            continue
        tcell = cells[cols["title"]]
        legacy = next((m[1] for href, _ in tcell.links if (m := _LEGACY_RE.search(href))), None)
        rank = parse_int(cells[cols["rank"]].text)
        if legacy is None:
            if rank is not None:
                out.unkeyed_rows += 1
            continue
        lw = cells[cols["lw"]].text.strip() if "lw" in cols else ""
        title = next((t for href, t in tcell.links if _LEGACY_RE.search(href) and t), tcell.text)
        out.rows.append(ChartRow(
            rank=rank,
            title=title,
            label=None,
            key=legacy.lower(),
            weekend_gross=parse_int(cells[cols["weekend_gross"]].text),
            theaters=parse_int(cells[cols["theaters"]].text) if "theaters" in cols else None,
            total_gross=parse_int(cells[cols["total_gross"]].text),
            weeks=parse_int(cells[cols["weeks"]].text) if "weeks" in cols else None,
            distributor=_text_or_none(cells[cols["distributor"]].text) if "distributor" in cols else None,
            is_new=(lw.upper() == "N") if lw else None,
            is_estimate=True if estimates else None,
        ))
    return out


# --- release page -------------------------------------------------------------

@dataclass
class ReleaseInfo:
    tt_id: str | None
    title: str | None
    release_date: date | None
    mpaa: str | None
    genres: str | None
    running_time: str | None
    distributor: str | None


_TITLE_LINK_RE = re.compile(r"^(?:https?://(?:www\.boxofficemojo\.com|pro\.imdb\.com))?/title/(tt\d{7,})(?:[/?#]|$)")
# Block elements whose start or end also ends an open <p> (HTML's implicit close).
_CLOSES_P = frozenset({"div", "section", "table", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "main", "form"})


class _Summary(HTMLParser):
    """Label/value pairs from ``div.mojo-summary-values`` (<div><span>Label</span><span>Value</span></div>)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.summary_depth: int | None = None
        self.item_depth: int | None = None
        self.span_depth: int | None = None
        self.items: list[dict] = []
        self.summary_title_ids: list[str] = []  # the "Title Summary" link: this release's own title
        self.title_ids: list[str] = []  # other title links outside running text
        self.h1: list[str] = []
        self._in_h1 = False
        self._in_p = False
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag in ("script", "style"):
            self._skip += 1
            return
        if tag == "p":
            self._in_p = True
        elif tag in _CLOSES_P:
            self._in_p = False
        href = a.get("href", "")
        m = _TITLE_LINK_RE.match(href)
        if m:
            # A synopsis can link to another film ("Five years after <a>Dominion</a>..."),
            # so links inside a paragraph never name the release.
            if "mojo-title-link" in a.get("class", "").split():
                self.summary_title_ids.append(m[1])
            elif not self._in_p:
                self.title_ids.append(m[1])
        if tag in htmltables.VOID:
            if tag == "br" and self.span_depth is not None and self.items:
                self.items[-1]["spans"][-1].append(" ")
            return
        self.depth += 1
        if tag == "h1":
            self._in_h1 = True
        classes = a.get("class", "").split()
        if self.summary_depth is None and "mojo-summary-values" in classes:
            self.summary_depth = self.depth
        elif self.summary_depth is not None and self.item_depth is None and self.depth == self.summary_depth + 1:
            self.item_depth = self.depth
            self.items.append({"spans": [], "hrefs": []})
        elif self.item_depth is not None and self.span_depth is None and self.depth == self.item_depth + 1:
            self.span_depth = self.depth
            self.items[-1]["spans"].append([])
        if self.item_depth is not None and href:
            self.items[-1]["hrefs"].append(href)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if tag in htmltables.VOID:
            return
        if tag == "h1":
            self._in_h1 = False
        if tag in ("p", *_CLOSES_P):
            self._in_p = False
        if self.span_depth is not None and self.depth == self.span_depth:
            self.span_depth = None
        if self.item_depth is not None and self.depth == self.item_depth:
            self.item_depth = None
        if self.summary_depth is not None and self.depth == self.summary_depth:
            self.summary_depth = -1  # done; only the first summary block counts
        self.depth -= 1

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_h1:
            self.h1.append(data)
        if self.span_depth is not None and self.items:
            self.items[-1]["spans"][-1].append(data)


_ISO_DATE_RE = re.compile(r"/date/(\d{4})-(\d{2})-(\d{2})")
_US_DATE_RE = re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s+(\d{4})")


def parse_release_page(html: str) -> ReleaseInfo:
    p = _Summary()
    p.feed(html)
    p.close()
    title_ids = p.summary_title_ids or p.title_ids
    if not p.items and not title_ids:
        raise NotAChart("no release summary or title link")
    fields: dict[str, tuple[str, list[str]]] = {}
    for item in p.items:
        spans = [squash("".join(s)) for s in item["spans"]]
        if len(spans) >= 2 and spans[0]:
            fields.setdefault(spans[0].lower(), (" ".join(spans[1:]), item["hrefs"]))

    def value(name: str) -> str | None:
        v = fields.get(name)
        return _text_or_none(v[0]) if v else None

    release_date = None
    if "release date" in fields:
        text, hrefs = fields["release date"]
        m = next((m for h in hrefs if (m := _ISO_DATE_RE.search(h))), None)
        if m:
            release_date = date(int(m[1]), int(m[2]), int(m[3]))
        elif (m := _US_DATE_RE.search(text)) and _MONTHS.get(m[1].lower()):
            release_date = date(int(m[3]), _MONTHS[m[1].lower()], int(m[2]))
    distributor = value("distributor")
    if distributor:
        distributor = re.sub(r"\s*See full company information\s*$", "", distributor) or None
    return ReleaseInfo(
        tt_id=title_ids[0] if title_ids else None,
        title=_text_or_none(squash("".join(p.h1))),
        release_date=release_date,
        mpaa=value("mpaa"),
        genres=value("genres"),
        running_time=value("running time"),
        distributor=distributor,
    )
