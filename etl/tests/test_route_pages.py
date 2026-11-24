"""route_pages: a page file for every route, so GitHub Pages answers 200 instead of 404."""

from __future__ import annotations

import re

import polars as pl
import pytest

from boffo_etl import paths, route_pages
from boffo_etl.build import REQUIRE_DATA_FLAG
from boffo_etl.match import TITLE_SCHEMA
from boffo_etl.sources.credits import PEOPLE_SCHEMA

SHELL = """<!doctype html>
<html lang="en">
  <head>
    <title>BoxOfficeBozo: Box office history, as it happened</title>
    <script type="module" crossorigin src="/assets/index-abc.js"></script>
  </head>
  <body><div id="root"></div></body>
</html>
"""


def _dist(tmp_path, titles=None, people=None):
    dist = tmp_path / "dist"
    (dist / "data").mkdir(parents=True)
    (dist / "index.html").write_text(SHELL, encoding="utf-8", newline="")
    if titles is not None:
        pl.DataFrame(titles, schema={k: TITLE_SCHEMA[k] for k in ("title_id", "title", "year")}).write_parquet(
            dist / "data" / "titles.parquet"
        )
    if people is not None:
        pl.DataFrame(people, schema={k: PEOPLE_SCHEMA[k] for k in ("person_id", "name")}).write_parquet(
            dist / "data" / "people.parquet"
        )
    return dist


def _title(path):
    return re.search(r"<title>(.*?)</title>", path.read_text(encoding="utf-8")).group(1)


def test_static_routes_match_the_app():
    app = (paths.repo_root() / "site" / "src" / "App.tsx").read_text(encoding="utf-8")
    routes = set(re.findall(r'<Route path="([^"]+)"', app))
    assert {r for r in routes if ":" not in r and r != "*"} == set(route_pages.STATIC_ROUTES)
    assert {r.split("/")[0] for r in routes if ":" in r} == set(route_pages.ID_ROUTES)


def test_film_page_title_matches_the_app():
    film = (paths.repo_root() / "site" / "src" / "pages" / "Film.tsx").read_text(encoding="utf-8")
    assert "f.year == null ? String(f.title) : `${String(f.title)} (${String(f.year)})`" in film
    assert route_pages.film_title("Titanic", 1997) == "Titanic (1997)"
    assert route_pages.film_title("Fantasia", None) == "Fantasia"


def test_writes_fixed_film_and_person_pages(tmp_path):
    dist = _dist(
        tmp_path,
        titles={"title_id": ["tt0120338", "bb_fantasia1940"], "title": ["Titanic", "Fantasia <&> \"1940\""], "year": [1997, None]},
        people={"person_id": ["Q42574", "Q1"], "name": ["James Cameron", None]},
    )
    counts = route_pages.write(dist)
    assert counts == {"fixed": len(route_pages.STATIC_ROUTES), "film": 2, "person": 2}

    for route in route_pages.STATIC_ROUTES:
        assert (dist / f"{route}.html").read_text(encoding="utf-8") == SHELL
    assert _title(dist / "film" / "tt0120338.html") == "Titanic (1997) - BoxOfficeBozo"
    assert _title(dist / "film" / "bb_fantasia1940.html") == "Fantasia &lt;&amp;&gt; &quot;1940&quot; - BoxOfficeBozo"
    assert _title(dist / "person" / "Q42574.html") == "James Cameron - BoxOfficeBozo"
    assert _title(dist / "person" / "Q1.html") == "Q1 - BoxOfficeBozo"  # no name: the ID, as the app shows
    # Everything but the <title> is the app shell, byte for byte.
    film = (dist / "film" / "tt0120338.html").read_text(encoding="utf-8")
    assert film.replace("Titanic (1997) - BoxOfficeBozo", "BoxOfficeBozo: Box office history, as it happened") == SHELL
    assert not (dist / "film" / "tt9999999.html").exists()


def test_rerun_drops_pages_for_ids_no_longer_shipped(tmp_path):
    dist = _dist(tmp_path, titles={"title_id": ["tt1", "tt2"], "title": ["A", "B"], "year": [2000, 2001]},
                 people={"person_id": ["Q1"], "name": ["X"]})
    route_pages.write(dist)
    pl.DataFrame({"title_id": ["tt1"], "title": ["A"], "year": [2000]},
                 schema={k: TITLE_SCHEMA[k] for k in ("title_id", "title", "year")}).write_parquet(dist / "data" / "titles.parquet")
    route_pages.write(dist)
    assert sorted(p.name for p in (dist / "film").iterdir()) == ["tt1.html"]


def test_without_tables_writes_only_the_fixed_routes(tmp_path, monkeypatch):
    monkeypatch.delenv(REQUIRE_DATA_FLAG, raising=False)
    dist = _dist(tmp_path)
    assert route_pages.write(dist) == {"fixed": len(route_pages.STATIC_ROUTES), "film": 0, "person": 0}
    assert (dist / "about.html").is_file()
    assert not (dist / "film").exists()


def test_without_tables_fails_when_data_is_required(tmp_path, monkeypatch):
    monkeypatch.setenv(REQUIRE_DATA_FLAG, "1")
    with pytest.raises(route_pages.RoutePagesError, match="titles.parquet"):
        route_pages.write(_dist(tmp_path))


def test_rejects_ids_that_cannot_be_file_names(tmp_path):
    dist = _dist(tmp_path, titles={"title_id": ["tt1", "../evil"], "title": ["A", "B"], "year": [2000, 2001]},
                 people={"person_id": ["Q1"], "name": ["X"]})
    with pytest.raises(route_pages.RoutePagesError, match="film IDs"):
        route_pages.write(dist)
    assert not (dist / "film").exists()


def test_needs_a_built_index(tmp_path):
    with pytest.raises(route_pages.RoutePagesError, match="vite build"):
        route_pages.write(tmp_path)


def test_main_reports_counts(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(paths, "site_dist", lambda: _dist(tmp_path, titles={"title_id": ["tt1"], "title": ["A"], "year": [2000]},
                                                         people={"person_id": ["Q1"], "name": ["X"]}))
    assert route_pages.main([]) == 0
    assert "1 film pages, 1 person pages" in capsys.readouterr().out
