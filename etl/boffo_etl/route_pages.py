"""Give every page of the built site its own file, so GitHub Pages answers 200 for it.

GitHub Pages has no rewrite rules. It serves ``/about`` from ``about.html`` when that file
exists; any other unknown path gets ``404.html`` with status 404. The site is a single-page
app and ``404.html`` is a copy of ``index.html`` (``site/scripts/spa-fallback.mjs``), so a deep
link still draws the right page, but with a 404 status: Lighthouse refuses to audit it, search
engines skip it, and link previews treat it as broken.

So after ``vite build`` this writes a copy of ``dist/index.html`` for each fixed route
(``about.html``, ``leaderboard.html``, ...) and for every film and person in the tables the
build ships (``film/<title_id>.html``, ``person/<qid>.html``), with that page's name in its
``<title>`` for crawlers and link previews that don't run JavaScript. An ID we don't have
still gets the real 404.

Run with ``python -m boffo_etl.route_pages`` (``make site-build`` runs it after ``vite build``).
"""

from __future__ import annotations

import html
import os
import re
import shutil
import sys
from pathlib import Path

import polars as pl

from . import paths
from .build import REQUIRE_DATA_FLAG

SITE = "BoxOfficeBozo"

# The fixed routes in site/src/App.tsx; a test checks the two lists match.
STATIC_ROUTES = ("films", "leaderboard", "people", "weekend", "search", "about")
# Routes with an ID, and the table and column the IDs come from.
ID_ROUTES = {"film": ("titles.parquet", "title_id"), "person": ("people.parquet", "person_id")}

SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
TITLE_TAG = re.compile(r"<title>.*?</title>", re.S)


class RoutePagesError(Exception):
    """The built site or its tables aren't what this step expects."""


def film_title(title: str, year: int | None) -> str:
    """The film page's title, as ``site/src/pages/Film.tsx`` sets it."""
    return title if year is None else f"{title} ({year})"


def page(shell: str, title: str | None) -> str:
    """The app shell with ``title`` in its <title>, the way ``useTitle`` writes it."""
    if title is None:
        return shell
    tag = f"<title>{html.escape(f'{title} - {SITE}')}</title>"
    return TITLE_TAG.sub(lambda _: tag, shell, count=1)


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")


def _id_pages(data: Path) -> dict[str, list[tuple[str, str]]]:
    """(id, page title) for every film and person in the shipped tables."""
    titles = pl.read_parquet(data / "titles.parquet", columns=["title_id", "title", "year"])
    people = pl.read_parquet(data / "people.parquet", columns=["person_id", "name"])
    pages = {
        "film": [(r["title_id"], film_title(r["title"], r["year"])) for r in titles.iter_rows(named=True)],
        "person": [(r["person_id"], r["name"] or r["person_id"]) for r in people.iter_rows(named=True)],
    }
    for route, rows in pages.items():
        bad = [i for i, _ in rows if not isinstance(i, str) or not SAFE_ID.match(i)]
        if bad:
            raise RoutePagesError(f"{len(bad)} {route} IDs can't be file names, e.g. {bad[:3]}")
    return pages


def write(dist: Path | None = None) -> dict[str, int]:
    """Write the route pages into ``dist``; returns how many of each kind."""
    dist = dist or paths.site_dist()
    index = dist / "index.html"
    if not index.is_file():
        raise RoutePagesError(f"{index} not found; run vite build first")
    shell = index.read_text(encoding="utf-8")
    if len(TITLE_TAG.findall(shell)) != 1:
        raise RoutePagesError(f"{index} should have exactly one <title>")

    for route in STATIC_ROUTES:
        _write(dist / f"{route}.html", shell)
    counts = {"fixed": len(STATIC_ROUTES), "film": 0, "person": 0}

    data = dist / "data"
    missing = [f for f, _ in ID_ROUTES.values() if not (data / f).is_file()]
    if missing:
        if os.environ.get(REQUIRE_DATA_FLAG) == "1":
            raise RoutePagesError(f"{REQUIRE_DATA_FLAG}=1 and {', '.join(missing)} missing from {data}")
        return counts

    for route, rows in _id_pages(data).items():
        folder = dist / route
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir()
        for page_id, title in rows:
            _write(folder / f"{page_id}.html", page(shell, title))
        counts[route] = len(rows)
    return counts


def main(argv: list[str] | None = None) -> int:
    try:
        counts = write()
    except (RoutePagesError, OSError, pl.exceptions.PolarsError) as exc:
        print(f"route-pages: {exc}", file=sys.stderr)
        return 1
    print(
        f"route-pages: {counts['fixed']} fixed routes, {counts['film']:,} film pages, "
        f"{counts['person']:,} person pages"
        + ("" if counts["film"] else " (no tables in dist/data, so no film or person pages)")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
