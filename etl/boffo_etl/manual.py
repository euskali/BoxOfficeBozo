"""Schemas, loader and validator for the hand-curated CSVs in data/manual/.

Every row needs a real, citable ``source``. Placeholder values are rejected.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Literal

from . import paths

PLACEHOLDER_SOURCES = frozenset(
    {
        "todo", "tbd", "tba", "unknown", "n/a", "na", "none", "null", "?", "-",
        "source", "citation needed", "xxx", "fixme", "guess", "made up", "placeholder",
    }
)
PLACEHOLDER_SUBSTRINGS = ("todo", "fixme")

QID_RE = re.compile(r"^Q\d+$")
TT_RE = re.compile(r"^tt\d{7,}$")
TITLE_ID_RE = re.compile(r"^(tt\d{7,}|bb_[a-z0-9_]+)$")


@dataclass(frozen=True)
class Issue:
    severity: Literal["error", "warning"]
    file: str
    line: int  # 1-based line number in the file; 0 when not row-specific
    message: str

    def __str__(self) -> str:
        loc = f"{self.file}:{self.line}" if self.line else self.file
        return f"{self.severity.upper():7} {loc}: {self.message}"


Row = dict[str, str]
Checker = Callable[[Row], str | None]


@dataclass(frozen=True)
class Schema:
    filename: str
    columns: tuple[str, ...]
    required: tuple[str, ...]
    types: dict[str, str]  # column -> informal type name (documentation + loader)
    primary_key: Callable[[Row], tuple]
    primary_key_desc: str
    row_checks: tuple[Checker, ...] = field(default_factory=tuple)


# --- cell-level helpers --------------------------------------------------

def _int_in(row: Row, col: str, lo: int | None = None, hi: int | None = None) -> str | None:
    raw = row[col].strip()
    try:
        val = int(raw)
    except ValueError:
        return f"{col} must be an integer, got {raw!r}"
    if lo is not None and val < lo:
        return f"{col} must be >= {lo}, got {val}"
    if hi is not None and val > hi:
        return f"{col} must be <= {hi}, got {val}"
    return None


def _pos_float(row: Row, col: str) -> str | None:
    raw = row[col].strip()
    try:
        val = float(raw)
    except ValueError:
        return f"{col} must be a number, got {raw!r}"
    if not val > 0 or val == float("inf"):
        return f"{col} must be a finite number > 0, got {raw!r}"
    return None


def _check_source(row: Row) -> str | None:
    raw = row["source"].strip()
    low = raw.lower()
    if not raw:
        return "source is required (a real, citable source)"
    if low in PLACEHOLDER_SOURCES or any(s in low for s in PLACEHOLDER_SUBSTRINGS):
        return f"source {raw!r} is a placeholder; cite a real source"
    return None


def _check_source_url(row: Row) -> str | None:
    raw = row.get("source_url", "").strip()
    if raw and not raw.lower().startswith(("http://", "https://")):
        return f"source_url must start with http:// or https://, got {raw!r}"
    return None


def _pattern(col: str, rx: re.Pattern[str], optional: bool = True) -> Checker:
    def check(row: Row) -> str | None:
        raw = row.get(col, "").strip()
        if not raw:
            return None if optional else f"{col} is required"
        if not rx.match(raw):
            return f"{col} {raw!r} does not match {rx.pattern}"
        return None

    return check


def _ticket_row(row: Row) -> str | None:
    return _int_in(row, "year", 1900, 2100) or _pos_float(row, "avg_price_usd")


def _baseline_row(row: Row) -> str | None:
    err = _int_in(row, "release_year", None, 1981) or _pos_float(row, "gross_usd")
    if err:
        return err
    raw = row["as_of"].strip()
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        return f"as_of must be an ISO date (YYYY-MM-DD), got {raw!r}"
    if d > date(1981, 12, 31):
        return f"as_of must be <= 1981-12-31, got {raw}"
    rental = row["is_rental"].strip()
    if rental not in ("true", "false"):
        return f"is_rental must be 'true' or 'false', got {rental!r}"
    return None


def _estimate_row(row: Row) -> str | None:
    err = _int_in(row, "admissions", 1, None)
    if err:
        return err
    raw = row["as_of"].strip()
    try:
        date.fromisoformat(raw)
    except ValueError:
        return f"as_of must be an ISO date (YYYY-MM-DD), got {raw!r}"
    return None


def _baseline_pk(row: Row) -> tuple:
    qid = row.get("wikidata_qid", "").strip()
    if qid:
        return ("qid", qid)
    return ("title", row.get("title", "").strip().lower(), row.get("release_year", "").strip())


SCHEMAS: dict[str, Schema] = {
    s.filename: s
    for s in (
        Schema(
            "ticket_prices.csv",
            ("year", "avg_price_usd", "source", "source_url", "notes"),
            ("year", "avg_price_usd", "source"),
            {"year": "int", "avg_price_usd": "float", "source": "str", "source_url": "str", "notes": "str"},
            lambda r: (r["year"].strip(),),
            "year",
            (_ticket_row, _check_source, _check_source_url),
        ),
        Schema(
            "pre1982_baseline.csv",
            ("title", "release_year", "wikidata_qid", "title_id", "gross_usd", "as_of",
             "is_rental", "source", "source_url", "notes"),
            ("title", "release_year", "gross_usd", "as_of", "is_rental", "source"),
            {"title": "str", "release_year": "int", "wikidata_qid": "str", "title_id": "str",
             "gross_usd": "float", "as_of": "date", "is_rental": "bool", "source": "str",
             "source_url": "str", "notes": "str"},
            _baseline_pk,
            "wikidata_qid if present, else (title, release_year)",
            (
                _baseline_row,
                _pattern("wikidata_qid", QID_RE),
                _pattern("title_id", TT_RE),
                _check_source,
                _check_source_url,
            ),
        ),
        Schema(
            # A published estimate of a baseline film's lifetime domestic admissions (tickets
            # sold) as of a date. cume.py prices the film's pre-1982 baseline with it.
            "admissions_estimates.csv",
            ("title", "title_id", "admissions", "as_of", "source", "source_url", "notes"),
            ("title", "title_id", "admissions", "as_of", "source"),
            {"title": "str", "title_id": "str", "admissions": "int", "as_of": "date",
             "source": "str", "source_url": "str", "notes": "str"},
            lambda r: (r["title_id"].strip(),),
            "title_id",
            (
                _estimate_row,
                _pattern("title_id", TT_RE, optional=False),
                _check_source,
                _check_source_url,
            ),
        ),
        Schema(
            "id_overrides.csv",
            ("source_key", "title_id", "wikidata_qid", "release_label", "source", "source_url", "notes"),
            ("source_key", "title_id", "source"),
            {c: "str" for c in ("source_key", "title_id", "wikidata_qid", "release_label",
                                "source", "source_url", "notes")},
            lambda r: (r["source_key"].strip(),),
            "source_key",
            (
                _pattern("title_id", TITLE_ID_RE, optional=False),
                _pattern("wikidata_qid", QID_RE),
                _check_source,
                _check_source_url,
            ),
        ),
        Schema(
            "title_groups.csv",
            ("source_key", "title_id", "release_label", "source", "source_url", "notes"),
            ("source_key", "title_id", "source"),
            {c: "str" for c in ("source_key", "title_id", "release_label", "source",
                                "source_url", "notes")},
            lambda r: (r["source_key"].strip(),),
            "source_key",
            (
                _pattern("title_id", TITLE_ID_RE, optional=False),
                _check_source,
                _check_source_url,
            ),
        ),
    )
}


def _convert(schema: Schema, row: Row) -> dict[str, object]:
    out: dict[str, object] = {}
    for col in schema.columns:
        raw = row[col].strip()
        kind = schema.types[col]
        if raw == "":
            out[col] = None
        elif kind == "int":
            out[col] = int(raw)
        elif kind == "float":
            out[col] = float(raw)
        elif kind == "date":
            out[col] = date.fromisoformat(raw)
        elif kind == "bool":
            out[col] = raw == "true"
        else:
            out[col] = raw
    return out


def _read_rows(path: Path) -> tuple[list[str] | None, list[tuple[int, Row]]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        rows: list[tuple[int, Row]] = []
        if header is None:
            return None, rows
        for rec in reader:
            if not rec or all(not c.strip() for c in rec):
                continue
            line = reader.line_num
            if len(rec) != len(header):
                rows.append((line, {"__bad_width__": str(len(rec))}))
                continue
            rows.append((line, dict(zip(header, rec))))
        return header, rows


def validate_file(path: Path) -> list[Issue]:
    schema = SCHEMAS[path.name]
    name = path.name
    issues: list[Issue] = []
    try:
        header, rows = _read_rows(path)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return [Issue("error", name, 0, f"cannot read file: {exc}")]
    if header is None:
        return [Issue("error", name, 0, f"file is empty; expected header {','.join(schema.columns)}")]
    if tuple(header) != schema.columns:
        return [Issue("error", name, 1,
                      f"header must be exactly {','.join(schema.columns)}; got {','.join(header)}")]
    seen: dict[tuple, int] = {}
    for line, row in rows:
        if "__bad_width__" in row:
            issues.append(Issue("error", name, line,
                                f"expected {len(schema.columns)} columns, got {row['__bad_width__']}"))
            continue
        missing = [c for c in schema.required if not row[c].strip()]
        for col in missing:
            issues.append(Issue("error", name, line, f"{col} is required"))
        row_ok = not missing
        if row_ok:
            for check in schema.row_checks:
                msg = check(row)
                if msg:
                    issues.append(Issue("error", name, line, msg))
                    row_ok = False
        if row_ok:
            key = schema.primary_key(row)
            if key in seen:
                issues.append(Issue("error", name, line,
                                    f"duplicate primary key ({schema.primary_key_desc}): {key} "
                                    f"(first seen on line {seen[key]})"))
            else:
                seen[key] = line
    return issues


def validate_manual_dir(path: Path | str | None = None) -> list[Issue]:
    directory = Path(path) if path is not None else paths.data_manual()
    issues: list[Issue] = []
    if not directory.is_dir():
        return [Issue("error", str(directory), 0, "manual data directory does not exist")]
    for name in SCHEMAS:
        if not (directory / name).is_file():
            issues.append(Issue("error", name, 0, "required manual CSV is missing"))
    for p in sorted(directory.glob("*.csv")):
        if p.name in SCHEMAS:
            issues.extend(validate_file(p))
        else:
            issues.append(Issue("warning", p.name, 0, "unknown CSV file in data/manual/ (no schema)"))
    return issues


def load_manual(name: str, path: Path | str | None = None) -> list[dict[str, object]]:
    """Load a validated manual CSV as typed dicts. Raises ValueError if invalid."""
    directory = Path(path) if path is not None else paths.data_manual()
    file = directory / name
    errors = [i for i in validate_file(file) if i.severity == "error"]
    if errors:
        raise ValueError("; ".join(str(e) for e in errors))
    schema = SCHEMAS[name]
    _, rows = _read_rows(file)
    return [_convert(schema, r) for _, r in rows]
