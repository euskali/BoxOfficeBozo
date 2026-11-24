"""M6: the site's ranking SQL, run from Python against the same Parquet.

The queries live in ``site/src/queries/*.sql`` and the browser runs the identical text in
DuckDB-WASM. Both sides pass parameters by position (``$1``, ``$2``...), in the order each file's
header documents; ``site/src/queries/index.ts`` mirrors these wrappers. The Python duckdb
package is pinned to the engine the pinned DuckDB-WASM bundles (``engine.json``), and tests
check that both report the same ``SELECT version()``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb

# The code checkout's queries, not BOFFO_REPO_ROOT's: that may point at a data-only directory.
SQL_DIR = Path(__file__).resolve().parents[2] / "site" / "src" / "queries"
TABLES = ("titles", "releases", "snapshots", "title_cume", "credits", "people", "cpi")
MEASURES = ("nominal", "cpi", "admissions")
TOP_BILLED = 4  # the default actor rollup rule (MVP_PLAN: top 4 billed)


def sql(name: str) -> str:
    return (SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")


def engine() -> dict:
    """The pinned DuckDB-WASM version and the engine version it bundles."""
    return json.loads((SQL_DIR / "engine.json").read_text(encoding="utf-8"))


def connect(data_dir: Path, tables: tuple[str, ...] = TABLES) -> duckdb.DuckDBPyConnection:
    """An in-memory connection with a view per Parquet table, named as the queries expect."""
    con = duckdb.connect()
    for name in tables:
        path = (Path(data_dir) / f"{name}.parquet").as_posix().replace("'", "''")
        con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{path}')")
    return con


def run(con: duckdb.DuckDBPyConnection, name: str, params: list) -> list[dict]:
    cur = con.execute(sql(name), params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _day(d: date | str) -> str:
    return d.isoformat() if isinstance(d, date) else d


def leaderboard(con, as_of: date | str, measure: str, limit: int = 100, offset: int = 0,
                from_year: int | None = None, to_year: int | None = None,
                title_id: str | None = None) -> list[dict]:
    return run(con, "leaderboard", [_day(as_of), measure, limit, offset, from_year, to_year, title_id])


def film_rank_timeline(con, title_id: str, measure: str) -> list[dict]:
    return run(con, "film_rank_timeline", [title_id, measure])


def person_totals(con, as_of: date | str, role: str, measure: str, top_billed: int = TOP_BILLED,
                  limit: int = 100, offset: int = 0, person_id: str | None = None) -> list[dict]:
    return run(con, "person_totals", [_day(as_of), role, measure, top_billed, limit, offset, person_id])


def person_rank(con, person_id: str, as_of: date | str, role: str, measure: str,
                top_billed: int = TOP_BILLED) -> dict | None:
    rows = person_totals(con, as_of, role, measure, top_billed, limit=1, person_id=person_id)
    return rows[0] if rows else None


def weekend_chart(con, on_date: date | str) -> list[dict]:
    return run(con, "weekend_chart", [_day(on_date)])


def cpi_factor(con, on_date: date | str) -> dict | None:
    rows = run(con, "cpi_factor", [_day(on_date)])
    return rows[0] if rows else None
