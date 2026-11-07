"""M3: film identity from Wikidata (CC0), queried through QLever.

QLever (https://qlever.dev, University of Freiburg) serves the full Wikidata
graph over SPARQL and answers big queries in seconds. The Wikidata Query
Service timed out (60 s) on the same per-year query, so it isn't used.

One snapshot per month, all through ``boffo_etl.fetch`` (cached, 5 s apart,
CI only). Each query carries a ``# BoxOfficeBozo Wikidata snapshot YYYY-MM``
comment, so it's a new URL each month and is cached for the rest of it:

* every item with a legacy Box Office Mojo film ID (P1237), and
* film items (instance of a subclass of Q11424) with an IMDb ID (P345) and a
  publication date (P577), one page per year from 1970 and per decade before.

Each item comes with its English label and aliases (``mul`` too), P345 ``tt``
ids, P1237 ids, sitelink count, and every non-deprecated P577 date with its
precision and place of publication (P291). Release-page ``tt`` ids that no
page returned are looked up by P345 directly.

If this month's snapshot can't be fetched, the newest complete cached one
(up to a year old) is used and the report says so. Once this month's is
complete, older snapshots are deleted from the raw cache.

Output, in ``data/build/``: ``wikidata_films.parquet`` (one row per item) and
``wikidata_report.json``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import polars as pl

from .. import paths
from ..fetch import Fetcher, FetchError, default_fetcher

ENDPOINT = "https://qlever.dev/api/wikidata"
FILM_CLASS = "Q11424"  # film
FIRST_YEAR = 1890  # one page for FIRST_YEAR..PER_YEAR_FROM-1, then one per year
PER_YEAR_FROM = 1910  # no year from 1910 has more than ~10k films with an IMDb id (2016, Nov 2026)
IMDB_BATCH = 50  # tt ids per P345 lookup (keeps the GET URL near 4 kB)
FALLBACK_MONTHS = 12
MARKER = "# BoxOfficeBozo Wikidata snapshot {stamp} ({what})"
MARKER_RE = re.compile(r"^# BoxOfficeBozo Wikidata snapshot (?P<stamp>\d{4}-\d{2}) ")
TT_RE = re.compile(r"^tt\d{7,}$")

PREFIXES = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX wikibase: <http://wikiba.se/ontology#>
"""

# The selector subquery picks the items; the rest describes each one, one row per item.
# Film pages join the dates (every item there has one); QLever's 30 s limit is hit when
# they are OPTIONAL. The P1237 and P345 lookups use the light form, with no dates.
FULL = """SELECT ?item (SAMPLE(?en) AS ?labelEn) (SAMPLE(?mul) AS ?labelMul) (SAMPLE(?sl) AS ?sitelinks)
  (GROUP_CONCAT(DISTINCT ?imdb; separator="|") AS ?imdbs)
  (GROUP_CONCAT(DISTINCT ?bom; separator="|") AS ?boms)
  (GROUP_CONCAT(DISTINCT ?date; separator="|") AS ?dates)
  (GROUP_CONCAT(DISTINCT ?alias; separator="|") AS ?aliases)
WHERE {{
  {{ {selector} }}
  ?item wdt:P345 ?imdb . FILTER(STRSTARTS(?imdb, "tt"))
  ?item p:P577 ?st . ?st wikibase:rank ?rank . FILTER(?rank != wikibase:DeprecatedRank)
  ?st psv:P577 ?tv . ?tv wikibase:timeValue ?t . ?tv wikibase:timePrecision ?prec .
  OPTIONAL {{ ?st pq:P291 ?place }}
  BIND(CONCAT(STR(?t), "/", STR(?prec), "/", COALESCE(STRAFTER(STR(?place), "entity/"), "")) AS ?date)
  OPTIONAL {{ ?item wdt:P1237 ?bom }}
  OPTIONAL {{ ?item wikibase:sitelinks ?sl }}
  OPTIONAL {{ ?item rdfs:label ?en . FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item rdfs:label ?mul . FILTER(LANG(?mul) = "mul") }}
  OPTIONAL {{ ?item skos:altLabel ?alias . FILTER(LANG(?alias) = "en" || LANG(?alias) = "mul") }}
}}
GROUP BY ?item"""
LIGHT = """SELECT ?item (SAMPLE(?en) AS ?labelEn) (SAMPLE(?mul) AS ?labelMul) (SAMPLE(?sl) AS ?sitelinks)
  (GROUP_CONCAT(DISTINCT ?imdb; separator="|") AS ?imdbs)
  (GROUP_CONCAT(DISTINCT ?bom; separator="|") AS ?boms)
WHERE {{
  {{ {selector} }}
  OPTIONAL {{ ?item wdt:P345 ?imdb . FILTER(STRSTARTS(?imdb, "tt")) }}
  OPTIONAL {{ ?item wdt:P1237 ?bom }}
  OPTIONAL {{ ?item wikibase:sitelinks ?sl }}
  OPTIONAL {{ ?item rdfs:label ?en . FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?item rdfs:label ?mul . FILTER(LANG(?mul) = "mul") }}
}}
GROUP BY ?item"""

FILMS_SELECTOR = (
    "SELECT DISTINCT ?item WHERE {{ ?item wdt:P31/wdt:P279* wd:{cls} . ?item wdt:P577 ?d0 . "
    "FILTER(YEAR(?d0) >= {y0} && YEAR(?d0) < {y1}) ?item wdt:P345 ?i0 . FILTER(STRSTARTS(?i0, \"tt\")) }}"
)
BOM_SELECTOR = "SELECT DISTINCT ?item WHERE { ?item wdt:P1237 ?b0 }"
IMDB_SELECTOR = "SELECT DISTINCT ?item WHERE {{ VALUES ?i0 {{ {values} }} ?item wdt:P345 ?i0 }}"

DATE_SCHEMA = pl.Struct({"date": pl.Date, "year": pl.Int32, "precision": pl.Int8, "place": pl.String})
FILM_SCHEMA = {
    "qid": pl.String, "tt": pl.String, "tts": pl.List(pl.String), "label": pl.String,
    "aliases": pl.List(pl.String), "sitelinks": pl.Int32, "dates": pl.List(DATE_SCHEMA),
    "bom_ids": pl.List(pl.String), "origin": pl.String,
}


# --- queries ---------------------------------------------------------------

def stamp_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def previous_stamps(d: date, months: int) -> list[str]:
    y, m, out = d.year, d.month, []
    for _ in range(months):
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        out.append(f"{y:04d}-{m:02d}")
    return out


def year_pages(last_year: int) -> list[tuple[int, int]]:
    """[y0, y1) publication-year ranges, each small enough for QLever's 30 s limit."""
    return [(FIRST_YEAR, PER_YEAR_FROM)] + [(y, y + 1) for y in range(PER_YEAR_FROM, last_year + 1)]


def build_query(selector: str, stamp: str, what: str, template: str) -> str:
    return MARKER.format(stamp=stamp, what=what) + "\n" + PREFIXES + template.format(selector=selector)


def films_what(y0: int, y1: int) -> str:
    return f"films {y0}" if y1 == y0 + 1 else f"films {y0}-{y1 - 1}"


def films_query(y0: int, y1: int, stamp: str) -> str:
    return build_query(FILMS_SELECTOR.format(cls=FILM_CLASS, y0=y0, y1=y1), stamp, films_what(y0, y1), FULL)


def bom_query(stamp: str) -> str:
    return build_query(BOM_SELECTOR, stamp, "P1237", LIGHT)


def imdb_query(tts: list[str], stamp: str) -> str:
    bad = [t for t in tts if not TT_RE.match(t)]
    if bad:
        raise ValueError(f"not IMDb title ids: {bad[:3]}")
    values = " ".join(f'"{t}"' for t in tts)
    return build_query(IMDB_SELECTOR.format(values=values), stamp, f"P345 {tts[0]}+{len(tts) - 1}", LIGHT)


def query_url(query: str) -> str:
    return f"{ENDPOINT}?{urlencode({'query': query})}"


@dataclass(frozen=True)
class Page:
    what: str
    url: str


def snapshot_pages(stamp: str) -> list[Page]:
    """Every query of one monthly snapshot (the P1237 list, then the film pages)."""
    last_year = int(stamp[:4]) + 1  # films dated next year, too
    pages = [Page("P1237", query_url(bom_query(stamp)))]
    pages += [Page(films_what(y0, y1), query_url(films_query(y0, y1, stamp))) for y0, y1 in year_pages(last_year)]
    return pages


# --- parsing ---------------------------------------------------------------

def parse_sparql_json(body: bytes) -> list[dict[str, str]]:
    """SPARQL JSON results -> one dict of plain values per row. ValueError if it isn't one."""
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"not JSON: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("results"), dict) \
            or not isinstance(doc["results"].get("bindings"), list) or "head" not in doc:
        raise ValueError("not a SPARQL JSON result")
    return [{k: v.get("value", "") for k, v in row.items()} for row in doc["results"]["bindings"]]


def validate_sparql(body: bytes) -> None:
    parse_sparql_json(body)


_TIME_RE = re.compile(r"^(?P<y>[+-]?\d{1,6})-(?P<m>\d{2})-(?P<d>\d{2})T")


def parse_date(value: str) -> dict | None:
    """'2015-11-20T00:00:00Z/11/Q30' -> {date, year, precision, place}. None if unreadable."""
    parts = value.split("/")
    if len(parts) != 3:
        return None
    t, prec, place = parts
    m = _TIME_RE.match(t)
    if not m:
        return None
    year = int(m["y"])
    try:
        precision = int(prec)
    except ValueError:
        return None
    if not 1 <= year <= 9999 or precision < 9:  # decade or coarser says nothing useful here
        return None
    d = None
    if precision >= 11:
        try:
            d = date(year, int(m["m"]), int(m["d"]))
        except ValueError:
            d = None
    return {"date": d, "year": year, "precision": precision, "place": place or None}


def _split(value: str | None) -> list[str]:
    return [v for v in (value or "").split("|") if v]


def norm_bom_id(value: str) -> str:
    """Legacy Box Office Mojo ids as stat695data spells them: lower case, no .htm suffix."""
    return re.sub(r"\.html?$", "", value.strip().lower())


def parse_items(rows: list[dict[str, str]], origin: str) -> list[dict]:
    out = []
    for r in rows:
        item = r.get("item", "")
        if not item.startswith("http://www.wikidata.org/entity/Q"):
            continue
        qid = item.rsplit("/", 1)[1]
        tts = sorted({t for t in _split(r.get("imdbs")) if TT_RE.match(t)})
        label = r.get("labelEn") or r.get("labelMul") or None
        aliases = sorted({a for a in _split(r.get("aliases")) if a != label})
        dates = [d for d in (parse_date(v) for v in _split(r.get("dates"))) if d is not None]
        dates.sort(key=lambda d: (d["year"], d["date"] or date.min, d["place"] or ""))
        try:
            sitelinks = int(r.get("sitelinks") or 0)
        except ValueError:
            sitelinks = 0
        out.append({
            "qid": qid, "tt": tts[0] if tts else None, "tts": tts, "label": label, "aliases": aliases,
            "sitelinks": sitelinks, "dates": dates,
            "bom_ids": sorted({norm_bom_id(b) for b in _split(r.get("boms")) if b.strip()}),
            "origin": origin,
        })
    return out


# --- the build step --------------------------------------------------------

@dataclass
class Snapshot:
    films: pl.DataFrame
    report: dict = field(default_factory=dict)


def _read(fetcher: Fetcher, page: Page) -> list[dict]:
    path = fetcher.fetch(page.url, suffix=".json", validate=validate_sparql)
    return parse_items(parse_sparql_json(path.read_bytes()), page.what)


def _complete(fetcher: Fetcher, stamp: str) -> bool:
    return all(fetcher.is_cached(p.url) for p in snapshot_pages(stamp))


def merge_items(items: list[dict]) -> pl.DataFrame:
    """One row per item. An item can come from several queries (the P1237 list and a film
    page, or two years' pages), the light ones without dates or aliases: lists are merged."""
    seen: dict[str, dict] = {}
    for it in items:
        cur = seen.get(it["qid"])
        if cur is None:
            seen[it["qid"]] = {**it, "tts": list(it["tts"]), "aliases": list(it["aliases"]),
                               "dates": list(it["dates"]), "bom_ids": list(it["bom_ids"])}
            continue
        for k in ("tts", "aliases", "bom_ids"):
            cur[k] = sorted(set(cur[k]) | set(it[k]))
        known = {(d["year"], d["date"], d["precision"], d["place"]) for d in cur["dates"]}
        cur["dates"] += [d for d in it["dates"] if (d["year"], d["date"], d["precision"], d["place"]) not in known]
        cur["dates"].sort(key=lambda d: (d["year"], d["date"] or date.min, d["place"] or ""))
        cur["tt"] = cur["tts"][0] if cur["tts"] else None
        cur["label"] = cur["label"] or it["label"]
        cur["sitelinks"] = max(cur["sitelinks"], it["sitelinks"])
        if cur["label"] in cur["aliases"]:
            cur["aliases"].remove(cur["label"])
    return pl.DataFrame(list(seen.values()), schema=FILM_SCHEMA).sort("qid")


def release_page_tts(build_dir: Path) -> list[str]:
    p = build_dir / "bom_release_pages.parquet"
    if not p.is_file():
        return []
    df = pl.read_parquet(p, columns=["tt_id"])
    return sorted({t for t in df["tt_id"].drop_nulls().to_list() if TT_RE.match(t)})


def prune_snapshots(keep: str) -> int:
    """Delete cached QLever answers of snapshots other than ``keep``. Returns how many."""
    directory = paths.data_raw() / "http" / (urlsplit(ENDPOINT).hostname or "")
    removed = 0
    if not directory.is_dir():
        return 0
    for meta in directory.glob("*.meta.json"):
        try:
            url = json.loads(meta.read_text(encoding="utf-8")).get("url", "")
        except (OSError, json.JSONDecodeError):
            continue
        query = parse_qs(urlsplit(url).query).get("query", [""])[0]
        m = MARKER_RE.match(query)
        if not m or m["stamp"] == keep:
            continue
        body = meta.with_name(meta.name.removesuffix(".meta.json"))
        body.unlink(missing_ok=True)
        meta.unlink(missing_ok=True)
        removed += 1
    return removed


def load_snapshot(fetcher: Fetcher, stamp: str, log=print) -> list[dict]:
    items: list[dict] = []
    pages = snapshot_pages(stamp)
    for i, page in enumerate(pages, 1):
        items.extend(_read(fetcher, page))
        if i % 20 == 0 or i == len(pages):
            log(f"  wikidata: snapshot {stamp}, {i}/{len(pages)} queries, {len(items)} rows, "
                f"{fetcher.network_requests} requests")
    return items


def ingest(fetcher: Fetcher, today: date, release_tts: list[str], log=print) -> Snapshot:
    current = stamp_of(today)
    stamp, stale_reason = current, None
    try:
        items = load_snapshot(fetcher, current, log)
    except FetchError as exc:  # FetchDisabledError too: offline, an older complete snapshot still works
        older = next((s for s in previous_stamps(today, FALLBACK_MONTHS) if _complete(fetcher, s)), None)
        if older is None:
            raise
        log(f"  wikidata: snapshot {current} unavailable ({exc}); using cached snapshot {older}")
        stamp, stale_reason = older, str(exc)
        items = load_snapshot(fetcher, older, log)

    films = merge_items(items)
    known = set(films.explode("tts")["tts"].drop_nulls().to_list())
    missing = [t for t in release_tts if t not in known]
    lookup = {"asked": len(missing), "found": 0, "error": None}
    extra: list[dict] = []
    for i in range(0, len(missing), IMDB_BATCH):
        batch = missing[i:i + IMDB_BATCH]
        try:
            extra.extend(_read(fetcher, Page("P345 lookup", query_url(imdb_query(batch, current)))))
        except FetchError as exc:
            lookup["error"] = str(exc)
            log(f"  wikidata: P345 lookup failed, {len(missing) - i} release-page tt ids left unresolved ({exc})")
            break
    if extra:
        films = merge_items(films.to_dicts() + extra)
        found = set(films.explode("tts")["tts"].drop_nulls().to_list())
        lookup["found"] = sum(1 for t in missing if t in found)

    pruned = prune_snapshots(current) if stale_reason is None else 0
    bom = films.filter(pl.col("bom_ids").list.len() > 0)
    multi_bom = (bom.explode("bom_ids").group_by("bom_ids").agg(pl.col("qid").sort())
                 .filter(pl.col("qid").list.len() > 1).sort("bom_ids"))
    multi_tt = (films.explode("tts").drop_nulls("tts").group_by("tts").agg(pl.col("qid").sort())
                .filter(pl.col("qid").list.len() > 1).sort("tts"))
    report = {
        "endpoint": ENDPOINT,
        "as_of": today.isoformat(),
        "snapshot": stamp,
        "stale_reason": stale_reason,
        "queries": len(snapshot_pages(stamp)),
        "items": films.height,
        "items_with_tt": int(films["tt"].is_not_null().sum()),
        "items_with_bom_id": bom.height,
        "bom_ids": int(bom["bom_ids"].list.len().sum()) if bom.height else 0,
        "bom_ids_on_several_items": [f"{r['bom_ids']}: {', '.join(r['qid'])}" for r in multi_bom.to_dicts()],
        "tts_on_several_items": [f"{r['tts']}: {', '.join(r['qid'])}" for r in multi_tt.head(200).to_dicts()],
        "tts_on_several_items_count": multi_tt.height,
        "release_page_tt_lookup": lookup,
        "pruned_cache_entries": pruned,
        "network_requests": fetcher.network_requests,
    }
    return Snapshot(films, report)


def write_outputs(snap: Snapshot, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    snap.films.write_parquet(out_dir / "wikidata_films.parquet")
    (out_dir / "wikidata_report.json").write_text(json.dumps(snap.report, indent=2) + "\n", encoding="utf-8")


def run(fetcher: Fetcher | None = None, today: date | None = None) -> Snapshot:
    """Build step: fetch this month's snapshot (CI only), write it to data/build/."""
    fetcher = fetcher or default_fetcher
    today = today or datetime.now(timezone.utc).date()
    snap = ingest(fetcher, today, release_page_tts(paths.data_build()))
    write_outputs(snap, paths.data_build())
    r = snap.report
    print(f"  wikidata: snapshot {r['snapshot']}{' (STALE)' if r['stale_reason'] else ''}: {r['items']} items, "
          f"{r['items_with_tt']} with an IMDb id, {r['bom_ids']} legacy Box Office Mojo ids on "
          f"{r['items_with_bom_id']} items; release-page tt lookup {r['release_page_tt_lookup']}; "
          f"{r['network_requests']} requests")
    return snap
