"""M4: directors and cast of the matched films, from Wikidata (CC0).

For every title with a Wikidata item (``titles.parquet``), highest-grossing first:

* **Statements**, from the Wikidata API's ``wbgetentities`` (www.wikidata.org),
  50 items a request: director (P57), cast member (P161) and voice actor
  (P725), in statement order, with any series-ordinal (P1545) qualifier.
  Animated films list their cast as voice actors (Toy Story has no P161).
  RDF, and so SPARQL, has no statement order, so this can't come from QLever.
  The API sends every claim of each film (about 90 kB a film), so only those
  three properties are kept in the raw cache.
* **People**, from QLever, 200 films a query: the English label (else
  ``mul``) and IMDb person id (P345) of everyone in those statements.

Requests carry the month (``requestid`` for the API, a marker comment for
QLever), so credits refresh monthly. A run fetches what this month's cache
lacks until its time budget runs out or a request fails; a film not fetched
yet this month uses its newest older answer. Once this month covers every
film, older months' answers are deleted from the raw cache.

Billing: a film's cast is its longer list of P161 and P725 statements, then
anyone only in the other. Actors with a P1545 ordinal come first, in ordinal
order, then the rest in statement order; ``billing`` is the position (1 is
top billed). Deprecated statements and unknown values are skipped. Directors
have no billing.

Writes ``people.parquet`` and ``credits.parquet`` to ``site/public/data/`` and
``credits_report.json`` to ``data/build/``.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import polars as pl

from .. import paths
from ..fetch import Fetcher, FetchDisabledError, FetchError, default_fetcher
from . import wikidata as wd

API = "https://www.wikidata.org/w/api.php"
CLAIMS_BATCH = 50  # wbgetentities' limit without bot rights
PEOPLE_BATCH = 200  # films a QLever people query: ~8 s and a ~4 kB URL for the 200 biggest (Nov 2026)
DIRECTOR, ACTOR = "director", "actor"
PROPS = ("P57", "P161", "P725")
ORDINAL = "P1545"
TOP_BILLED = 4  # the actor rollup rule's default: a film counts for its top 4 billed actors (M6)
TOP_TITLES = 1000
ENV_MINUTES = "BOFFO_CREDITS_MINUTES"
DEFAULT_MINUTES = 45.0  # a full month's refresh takes ~40 min (Nov 2026)
REQUEST_ID = "BoxOfficeBozo-credits-{stamp}"
REQUEST_ID_RE = re.compile(r"^BoxOfficeBozo-credits-(?P<stamp>\d{4}-\d{2})$")
MARKER = "# BoxOfficeBozo Wikidata credits {stamp} ({what})"  # not wikidata.MARKER_RE: M3's pruning skips it
MARKER_RE = re.compile(r"^# BoxOfficeBozo Wikidata credits (?P<stamp>\d{4}-\d{2}) ")
VALUES_RE = re.compile(r"VALUES \?film \{([^}]*)\}")
QID_RE = re.compile(r"^Q\d+$")
NM_RE = re.compile(r"^nm\d{7,}$")
ENTITY = "http://www.wikidata.org/entity/"

PEOPLE = """SELECT ?person (GROUP_CONCAT(DISTINCT ?en; separator="|") AS ?labelEn)
  (GROUP_CONCAT(DISTINCT ?mul; separator="|") AS ?labelMul)
  (GROUP_CONCAT(DISTINCT ?nm; separator="|") AS ?imdbs)
WHERE {{
  {{ SELECT DISTINCT ?person WHERE {{
    VALUES ?film {{ {values} }}
    ?film p:P57|p:P161|p:P725 ?st . ?st ps:P57|ps:P161|ps:P725 ?person .
    FILTER(STRSTARTS(STR(?person), "http://www.wikidata.org/entity/Q")) }} }}
  OPTIONAL {{ ?person wdt:P345 ?nm . FILTER(STRSTARTS(?nm, "nm")) }}
  OPTIONAL {{ ?person rdfs:label ?en . FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?person rdfs:label ?mul . FILTER(LANG(?mul) = "mul") }}
}}
GROUP BY ?person"""

CREDITS_SCHEMA = {"title_id": pl.String, "person_id": pl.String, "role": pl.String, "billing": pl.Int32,
                  "billing_source": pl.String}
PEOPLE_SCHEMA = {"person_id": pl.String, "imdb_id": pl.String, "name": pl.String}


# --- requests ------------------------------------------------------------------

def _check_qids(qids: list[str]) -> None:
    bad = [q for q in qids if not QID_RE.match(q)]
    if bad or not qids:
        raise ValueError(f"not Wikidata item ids: {bad[:3] or 'none given'}")


def claims_url(qids: list[str], stamp: str) -> str:
    _check_qids(qids)
    return API + "?" + urlencode({"action": "wbgetentities", "format": "json", "props": "claims",
                                  "ids": "|".join(qids), "requestid": REQUEST_ID.format(stamp=stamp)})


def people_query(qids: list[str], stamp: str) -> str:
    _check_qids(qids)
    marker = MARKER.format(stamp=stamp, what=f"people {qids[0]}+{len(qids) - 1}")
    prefixes = wd.PREFIXES + "PREFIX ps: <http://www.wikidata.org/prop/statement/>\n"
    return marker + "\n" + prefixes + PEOPLE.format(values=" ".join(f"wd:{q}" for q in qids))


def people_url(qids: list[str], stamp: str) -> str:
    return wd.query_url(people_query(qids, stamp))


def parse_request(url: str) -> tuple[str, str, tuple[str, ...]] | None:
    """(kind, month, film ids) of one of our cached credits requests, else None."""
    query = parse_qs(urlsplit(url).query)
    if url.startswith(API + "?"):
        m = REQUEST_ID_RE.match(query.get("requestid", [""])[0])
        if not m or query.get("action") != ["wbgetentities"]:
            return None
        return "claims", m["stamp"], tuple(query.get("ids", [""])[0].split("|"))
    if url.startswith(wd.ENDPOINT + "?"):
        text = query.get("query", [""])[0]
        m, values = MARKER_RE.match(text), VALUES_RE.search(text)
        if not m or not values:
            return None
        return "people", m["stamp"], tuple(re.findall(r"wd:(Q\d+)", values[1]))
    return None


# --- the API's answer --------------------------------------------------------

def _api_doc(body: bytes) -> dict:
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"not JSON: {exc}") from exc
    if not isinstance(doc, dict) or "error" in doc or not isinstance(doc.get("entities"), dict):
        raise ValueError(f"not a wbgetentities answer: {str(doc.get('error') if isinstance(doc, dict) else doc)[:200]}")
    return doc


def validate_claims(body: bytes) -> None:
    _api_doc(body)


def _statement(claim: dict) -> list:
    """[value item id or None, rank, P1545 ordinal or None], in the claim's own order."""
    snak = claim.get("mainsnak") or {}
    value = (snak.get("datavalue") or {}).get("value") if snak.get("snaktype") == "value" else None
    qid = value.get("id") if isinstance(value, dict) else None
    ordinals = [(q.get("datavalue") or {}).get("value") for q in (claim.get("qualifiers") or {}).get(ORDINAL, [])
                if q.get("snaktype") == "value"]
    return [qid, claim.get("rank", "normal"), next((o for o in ordinals if isinstance(o, str)), None)]


def reduce_claims(body: bytes) -> bytes:
    """Keep each entity's P57, P161 and P725 statements (in order); drop every other claim."""
    out: dict[str, dict] = {}
    for key, ent in _api_doc(body)["entities"].items():
        rec: dict = {"id": ent.get("id") or key}
        if "missing" in ent:
            rec["missing"] = True
        claims = ent.get("claims") or {}
        for prop in PROPS:
            rec[prop] = [_statement(c) for c in claims.get(prop, [])]
        out[key] = rec
        source = (ent.get("redirects") or {}).get("from")
        if source:
            out.setdefault(source, rec)
    return json.dumps({"entities": out}, separators=(",", ":"), sort_keys=True).encode("utf-8")


def load_claims(path: Path) -> dict[str, dict]:
    body = path.read_bytes()
    doc = json.loads(body.decode("utf-8"))
    if any("claims" in e for e in doc.get("entities", {}).values()):  # an unreduced answer
        doc = json.loads(reduce_claims(body).decode("utf-8"))
    return doc["entities"]


def parse_people(rows: list[dict[str, str]]) -> dict[str, dict]:
    """QLever rows -> person id -> {person_id, imdb_id, name}. English label, else mul; a bare
    item id isn't a name (QLever can return one as an English label: see wikidata.py)."""
    out = {}
    for r in rows:
        item = r.get("person", "")
        if not item.startswith(ENTITY + "Q"):
            continue
        qid = item.removeprefix(ENTITY)
        labels = [v for key in ("labelEn", "labelMul") for v in sorted(_split(r.get(key))) if not QID_RE.match(v)]
        nms = sorted(n for n in _split(r.get("imdbs")) if NM_RE.match(n))
        out[qid] = {"person_id": qid, "imdb_id": nms[0] if nms else None, "name": labels[0] if labels else None}
    return out


def _split(value: str | None) -> list[str]:
    return [v for v in (value or "").split("|") if v]


# --- credits -------------------------------------------------------------------

def _ordinal(value: str | None) -> int | None:
    try:
        n = int((value or "").strip())
    except ValueError:
        return None
    return n if n >= 0 else None


def _usable(statements: list) -> list:
    return [s for s in statements if s[0] and QID_RE.match(s[0]) and s[1] != "deprecated"]


def film_credits(title_id: str, rec: dict) -> list[dict]:
    """One film's credit rows: directors, then actors in billing order."""
    rows = []
    directors: list[str] = []
    for qid, _, _ in _usable(rec.get("P57", [])):
        if qid not in directors:
            directors.append(qid)
            rows.append({"title_id": title_id, "person_id": qid, "role": DIRECTOR, "billing": None,
                         "billing_source": None})
    cast, voices = _usable(rec.get("P161", [])), _usable(rec.get("P725", []))
    first, second = (voices, cast) if len(voices) > len(cast) else (cast, voices)
    actors: dict[str, int | None] = {}  # person -> ordinal, in statement order
    for qid, _, ordinal in first + second:
        if qid not in actors:
            actors[qid] = _ordinal(ordinal)
        elif actors[qid] is None:
            actors[qid] = _ordinal(ordinal)
    order = sorted(enumerate(actors.items()), key=lambda x: (x[1][1] is None, x[1][1] or 0, x[0]))
    for billing, (_, (qid, ordinal)) in enumerate(order, 1):
        rows.append({"title_id": title_id, "person_id": qid, "role": ACTOR, "billing": billing,
                     "billing_source": "p1545" if ordinal is not None else "statement_order"})
    return rows


# --- the cache -----------------------------------------------------------------

@dataclass(frozen=True)
class Entry:
    kind: str  # "claims" or "people"
    stamp: str
    qids: tuple[str, ...]
    path: Path


def cached_entries() -> list[Entry]:
    """Every complete credits answer in the raw cache, oldest month first."""
    out = []
    for url in (API, wd.ENDPOINT):
        directory = paths.data_raw() / "http" / (urlsplit(url).hostname or "")
        if not directory.is_dir():
            continue
        for meta in sorted(directory.glob("*.meta.json")):
            try:
                request = json.loads(meta.read_text(encoding="utf-8")).get("url", "")
            except (OSError, json.JSONDecodeError):
                continue
            parsed = parse_request(request)
            body = meta.with_name(meta.name.removesuffix(".meta.json"))
            if parsed and body.is_file():  # the body is written last: it marks a complete entry
                out.append(Entry(*parsed, body))
    return sorted(out, key=lambda e: (e.stamp, e.kind, str(e.path)))


def _covered(entries: list[Entry], kind: str, stamp: str) -> set[str]:
    return {q for e in entries if e.kind == kind and e.stamp == stamp for q in e.qids}


def fetch_month(fetcher: Fetcher, qids: list[str], stamp: str, deadline: float, log=print) -> dict:
    """Fetch what this month's cache lacks, biggest films first, until the deadline or an error."""
    entries = cached_entries()
    position = {q: i for i, q in enumerate(qids)}
    plan = []
    for kind, size in (("claims", CLAIMS_BATCH), ("people", PEOPLE_BATCH)):
        have = _covered(entries, kind, stamp)
        need = [q for q in qids if q not in have]
        plan += [(position[need[i]], kind, need[i:i + size]) for i in range(0, len(need), size)]
    plan.sort(key=lambda p: (p[0], p[1]))  # claims before people for the same films
    stats = {"planned": len(plan), "done": 0, "stopped": None}
    for _, kind, batch in plan:
        if time.monotonic() >= deadline:
            stats["stopped"] = "time budget"
            break
        try:
            if kind == "claims":
                fetcher.fetch(claims_url(batch, stamp), suffix=".json", validate=validate_claims,
                              reduce=reduce_claims)
            else:
                fetcher.fetch(people_url(batch, stamp), suffix=".json", validate=wd.validate_sparql)
        except FetchDisabledError:
            stats["stopped"] = "fetching disabled"
            break
        except FetchError as exc:
            stats["stopped"] = f"error: {exc}"[:300]
            log(f"  credits: stopped fetching after {stats['done']} of {len(plan)} requests ({exc})")
            break
        stats["done"] += 1
        if stats["done"] % 25 == 0:
            log(f"  credits: {stats['done']}/{len(plan)} requests, {fetcher.network_requests} sent")
    return stats


def prune(entries: list[Entry], keep_stamp: str) -> int:
    """Delete cached credits answers from months other than ``keep_stamp``."""
    removed = 0
    for e in entries:
        if e.stamp != keep_stamp:
            e.path.with_name(e.path.name + ".meta.json").unlink(missing_ok=True)
            e.path.unlink(missing_ok=True)
            removed += 1
    return removed


# --- the build step --------------------------------------------------------------

@dataclass(frozen=True)
class Film:
    title_id: str
    qid: str
    title: str | None
    gross: int


@dataclass
class Credits:
    people: pl.DataFrame
    credits: pl.DataFrame
    report: dict


def ingest(fetcher: Fetcher, films: list[Film], today: date, deadline: float, log=print) -> Credits:
    """``films`` biggest first. Raises FetchDisabledError when offline with nothing cached."""
    stamp = wd.stamp_of(today)
    wanted = list(dict.fromkeys(f.qid for f in films))
    stats = fetch_month(fetcher, wanted, stamp, deadline, log)

    entries = cached_entries()
    wanted_set = set(wanted)
    claims: dict[str, tuple[str, dict]] = {}
    people: dict[str, dict] = {}
    for e in entries:  # oldest month first: the newest answer wins
        if e.kind == "claims" and wanted_set.intersection(e.qids):
            for key, rec in load_claims(e.path).items():
                if key in wanted_set:
                    claims[key] = (e.stamp, rec)
        elif e.kind == "people" and wanted_set.intersection(e.qids):
            people.update(parse_people(wd.parse_sparql_json(e.path.read_bytes())))
    if not claims and stats["stopped"] == "fetching disabled":
        raise FetchDisabledError("Wikidata credits are not cached in data/raw/ (they are fetched in CI)")

    current = _covered(entries, "claims", stamp) & _covered(entries, "people", stamp)
    complete = wanted_set <= current
    pruned = prune(entries, stamp) if complete else 0

    rows: list[dict] = []
    no_data, missing_items, stale, voice_films = [], [], 0, 0
    for f in films:
        got = claims.get(f.qid)
        if got is None:
            no_data.append(f)
            continue
        month, rec = got
        stale += month != stamp
        if rec.get("missing"):
            missing_items.append(f)
            continue
        voice_films += len(_usable(rec.get("P725", []))) > len(_usable(rec.get("P161", [])))
        rows.extend(film_credits(f.title_id, rec))
    credits = (pl.DataFrame(rows, schema=CREDITS_SCHEMA)
               .sort("title_id", "role", "billing", "person_id", nulls_last=True))
    person_ids = sorted(set(credits["person_id"].to_list()))
    people_df = pl.DataFrame([people.get(p) or {"person_id": p, "imdb_id": None, "name": None} for p in person_ids],
                             schema=PEOPLE_SCHEMA)
    report = _report(films, credits, people_df, stamp, today, stats, complete, stale, no_data, missing_items,
                     voice_films, pruned, fetcher)
    return Credits(people_df, credits, report)


def _titles_line(f: Film) -> dict:
    return {"title_id": f.title_id, "title": f.title, "gross": f.gross}


def _report(films, credits, people, stamp, today, stats, complete, stale, no_data, missing_items, voice_films,
            pruned, fetcher) -> dict:
    per_title = credits.group_by("title_id").agg(
        (pl.col("role") == DIRECTOR).sum().alias("directors"), (pl.col("role") == ACTOR).sum().alias("actors"))
    directors = set(per_title.filter(pl.col("directors") > 0)["title_id"].to_list())
    full_cast = set(per_title.filter(pl.col("actors") >= TOP_BILLED)["title_id"].to_list())
    fetched = {f.title_id for f in films} - {f.title_id for f in no_data}
    top = films[:TOP_TITLES]
    n = len(films) or 1
    return {
        "as_of": today.isoformat(),
        "month": stamp,
        "month_complete": complete,
        "fetch": stats,
        "network_requests": fetcher.network_requests,
        "films": len(films),
        "films_with_statements": len(fetched),
        "films_from_older_month": stale,
        "films_without_statements": len(no_data),
        "films_without_statements_examples": [_titles_line(f) for f in no_data[:20]],
        "items_missing_on_wikidata": [_titles_line(f) for f in missing_items[:50]],
        "voice_cast_films": voice_films,
        "credits": credits.height,
        "director_credits": int((credits["role"] == DIRECTOR).sum()),
        "actor_credits": int((credits["role"] == ACTOR).sum()),
        "billing_source": {k: int((credits["billing_source"] == k).sum()) for k in ("p1545", "statement_order")},
        "people": people.height,
        "people_with_imdb_id": int(people["imdb_id"].is_not_null().sum()),
        "people_without_name": int(people["name"].is_null().sum()),
        "people_without_name_examples": people.filter(pl.col("name").is_null())["person_id"].head(20).to_list(),
        "top_billed": TOP_BILLED,
        "films_with_director": len(directors),
        "films_with_director_share": len(directors) / n,
        "films_with_top_billed_cast": len(full_cast),
        "films_with_top_billed_cast_share": len(full_cast) / n,
        "top_titles": TOP_TITLES,
        "top_without_director": [_titles_line(f) for f in top if f.title_id in fetched and f.title_id not in directors],
        "top_without_statements": len([f for f in top if f.title_id not in fetched]),
        "pruned_cache_entries": pruned,
    }


def matched_films(site_dir: Path) -> list[Film]:
    """Titles with a Wikidata item, biggest total gross first (every release's latest total, plus
    any pre-1982 baseline)."""
    titles = pl.read_parquet(site_dir / "titles.parquet")
    gross = (pl.read_parquet(site_dir / "snapshots.parquet", columns=["release_id", "total_gross"])
             .group_by("release_id").agg(pl.col("total_gross").max())
             .join(pl.read_parquet(site_dir / "releases.parquet", columns=["release_id", "title_id"]), on="release_id")
             .group_by("title_id").agg(pl.col("total_gross").sum().alias("gross")))
    rows = (titles.join(gross, on="title_id", how="left")
            .with_columns((pl.col("gross").fill_null(0) + pl.col("pre1982_baseline_gross").fill_null(0)).alias("gross"))
            .filter(pl.col("wikidata_qid").is_not_null())
            .sort(["gross", "title_id"], descending=[True, False]))
    return [Film(r["title_id"], r["wikidata_qid"], r["title"], int(r["gross"] or 0)) for r in rows.to_dicts()]


def _env_minutes() -> float:
    try:
        return float(os.environ.get(ENV_MINUTES, DEFAULT_MINUTES))
    except ValueError:
        return DEFAULT_MINUTES


def run(fetcher: Fetcher | None = None, today: date | None = None, deadline: float | None = None) -> list[Path]:
    """Build step, after matching: write people.parquet and credits.parquet. ``deadline``
    (time.monotonic()) caps this step's own budget, so the whole build fits its job."""
    fetcher = fetcher or default_fetcher
    today = today or datetime.now(timezone.utc).date()
    site_dir, build_dir = paths.site_data(), paths.data_build()
    films = matched_films(site_dir)
    if not films:
        print("  credits: no titles are matched to Wikidata items, so there are no credits to build")
        return []
    own = time.monotonic() + _env_minutes() * 60
    result = ingest(fetcher, films, today, min(own, deadline) if deadline is not None else own)
    out = [site_dir / "people.parquet", site_dir / "credits.parquet"]
    result.people.write_parquet(out[0])
    result.credits.write_parquet(out[1])
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "credits_report.json").write_text(json.dumps(result.report, indent=2) + "\n", encoding="utf-8")
    r = result.report
    print(f"  credits: month {r['month']}{'' if r['month_complete'] else ' (incomplete)'}: statements for "
          f"{r['films_with_statements']} of {r['films']} films ({r['films_from_older_month']} from an older month); "
          f"{r['credits']} credits, {r['people']} people; {r['films_with_director_share']:.1%} of films have a "
          f"director, {r['films_with_top_billed_cast_share']:.1%} at least {TOP_BILLED} cast; "
          f"{len(r['top_without_director'])} of the top {TOP_TITLES} have no director; "
          f"{r['network_requests']} requests; fetch {r['fetch']}")
    return out
