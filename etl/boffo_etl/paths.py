"""Repository paths.

All paths are computed by functions at call time so tests can point the ETL at a
temporary repo by setting the ``BOFFO_REPO_ROOT`` environment variable.
"""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    override = os.environ.get("BOFFO_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def data_raw() -> Path:
    return repo_root() / "data" / "raw"


def data_build() -> Path:
    return repo_root() / "data" / "build"


def data_manual() -> Path:
    return repo_root() / "data" / "manual"


def site_data() -> Path:
    return repo_root() / "site" / "public" / "data"


def site_queries() -> Path:
    return repo_root() / "site" / "src" / "queries"


def site_dist() -> Path:
    return repo_root() / "site" / "dist"


# Upper-case aliases (callables, evaluated at call time).
REPO_ROOT = repo_root
DATA_RAW = data_raw
DATA_BUILD = data_build
DATA_MANUAL = data_manual
SITE_DATA = site_data
SITE_QUERIES = site_queries
