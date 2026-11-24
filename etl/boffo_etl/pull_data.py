"""``make pull-data``: copy the tables the live site publishes into site/public/data.

For working on the site with the real data: the ETL can't fetch its sources locally, but the
deployed site already serves every built table (https://boxofficebozo.com/data/). This reads
that manifest, downloads each table it lists, checks each file's size and SHA-256 against it,
and writes them with the manifest. It fetches only from the site (``BOFFO_SITE_URL`` points it at
another deployment), never from a data source. The files stay gitignored, like built data.

Run with ``python -m boffo_etl.pull_data``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from urllib.parse import urljoin, urlsplit

import httpx

from . import paths
from .fetch import DENYLIST, USER_AGENT

SITE_URL_FLAG = "BOFFO_SITE_URL"
DEFAULT_SITE = "https://boxofficebozo.com/"


class PullError(Exception):
    """The published data couldn't be copied (bad URL, HTTP error, or a checksum mismatch)."""


def _site() -> str:
    site = os.environ.get(SITE_URL_FLAG) or DEFAULT_SITE
    host = (urlsplit(site).hostname or "").lower()
    if urlsplit(site).scheme not in ("https", "http") or not host:
        raise PullError(f"{SITE_URL_FLAG}={site!r} is not an http(s) URL")
    if any(host == d or host.endswith("." + d) for d in DENYLIST):
        raise PullError(f"{host} is on the fetch denylist")
    return site if site.endswith("/") else site + "/"


def _get(client: httpx.Client, url: str) -> bytes:
    res = client.get(url)
    if res.status_code != 200:
        raise PullError(f"{url}: HTTP {res.status_code}")
    return res.content


def pull(client: httpx.Client | None = None) -> list[dict]:
    """Downloads the published tables into site/public/data; returns the manifest's table entries."""
    base = urljoin(_site(), "data/")
    own = client is None
    # No redirects: the site serves these directly, and a redirect could lead anywhere.
    client = client or httpx.Client(timeout=120.0, headers={"User-Agent": USER_AGENT}, follow_redirects=False)
    try:
        raw = _get(client, urljoin(base, "manifest.json"))
        manifest = json.loads(raw)
        if manifest.get("sample"):
            raise PullError(f"{base}manifest.json is sample data")
        tables = manifest.get("tables") or []
        if not tables:
            raise PullError(f"{base}manifest.json lists no tables")
        files = {}
        for t in tables:
            name = t["file"]
            if "/" in name or "\\" in name or not name.endswith(".parquet"):
                raise PullError(f"unexpected file name in the manifest: {name!r}")
            data = _get(client, urljoin(base, name))
            if len(data) != t["bytes"] or hashlib.sha256(data).hexdigest() != t["sha256"]:
                raise PullError(f"{name}: size or checksum doesn't match the manifest")
            files[name] = data
    finally:
        if own:
            client.close()
    out = paths.site_data()
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (out / name).write_bytes(data)
    (out / "manifest.json").write_bytes(raw)
    return tables


def main(argv: list[str] | None = None) -> int:
    try:
        tables = pull()
    except (PullError, httpx.HTTPError, ValueError, KeyError) as exc:
        print(f"pull-data: {exc}", file=sys.stderr)
        return 1
    for t in tables:
        print(f"pull-data: {t['file']} ({t['rows']} rows)")
    print(f"pull-data: copied the published data into {paths.site_data()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
