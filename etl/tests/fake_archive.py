"""An in-memory stand-in for the Wayback Machine and Common Crawl, for httpx.MockTransport."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

import httpx

from bom_html import cc_index_lines, cdx_json, warc_record


def canonical(url: str) -> str:
    u = re.sub(r"^https?://", "", url.strip().lower())
    u = u.removeprefix("www.").replace(":80/", "/")
    return u.rstrip("/")


class FakeArchive:
    def __init__(self) -> None:
        self.wayback: dict[str, list[tuple[str, str]]] = {}
        self.pages: dict[str, str] = {}
        self.crawls: list[dict] = []
        self.cc: dict[tuple[str, str], list[dict]] = {}
        self.warcs: dict[str, bytes] = {}
        self.fail: list[str] = []  # URL substrings answered with HTTP 503
        self.fail_times: dict[str, int] = {}  # ...for the first n matching requests only
        self.requests: list[str] = []

    # -- setup -------------------------------------------------------------
    def add_wayback(self, original: str, ts: str, html: str) -> None:
        self.wayback.setdefault(canonical(original), []).append((ts, original))
        self.pages[f"/web/{ts}id_/{original}"] = html

    def add_crawl(self, crawl_id: str, start: str, end: str) -> None:
        self.crawls.append({"id": crawl_id, "name": crawl_id, "from": start, "to": end,
                            "cdx-api": f"https://index.commoncrawl.org/{crawl_id}-index",
                            "timegate": f"https://index.commoncrawl.org/{crawl_id}/"})

    def add_cc(self, crawl_id: str, original: str, ts: str, html: str, *, status: int = 200) -> None:
        filename = f"crawl-data/{crawl_id}/segments/1/warc/file-{len(self.warcs)}.warc.gz"
        padding = b"\x00" * 37  # the record sits mid-file, as real ones do
        record = warc_record(html, status=status)
        self.warcs[filename] = padding + record + b"\x00" * 11
        self.cc.setdefault((crawl_id, canonical(original)), []).append({
            "urlkey": canonical(original), "timestamp": ts, "url": original, "mime": "text/html",
            "mime-detected": "text/html", "status": str(status), "digest": "X", "length": str(len(record)),
            "offset": str(len(padding)), "filename": filename})

    # -- transport -----------------------------------------------------------
    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if any(f in url for f in self.fail):
            return httpx.Response(503, text="Temporarily Offline")
        for f, n in self.fail_times.items():
            if f in url and n > 0:
                self.fail_times[f] = n - 1
                return httpx.Response(503, text="Temporarily Offline")
        parts = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
        host = parts.hostname
        if host == "web.archive.org" and parts.path == "/cdx/search/cdx":
            caps = self.wayback.get(canonical(q["url"]), [])
            lo, hi = q.get("from", ""), q.get("to", "")
            caps = [(ts, o) for ts, o in caps if ts[:len(lo)] >= lo and (not hi or ts[:len(hi)] <= hi)]
            return httpx.Response(200, content=cdx_json(sorted(caps)), headers={"content-type": "text/plain"})
        if host == "web.archive.org" and parts.path.startswith("/web/"):
            key = url.removeprefix("https://web.archive.org")
            if key in self.pages:
                return httpx.Response(200, text=self.pages[key], headers={"content-type": "text/html"})
            return httpx.Response(404, text="not archived")
        if host == "index.commoncrawl.org" and parts.path == "/collinfo.json":
            return httpx.Response(200, text=json.dumps(self.crawls), headers={"content-type": "application/json"})
        if host == "index.commoncrawl.org" and parts.path.endswith("-index"):
            crawl = parts.path.strip("/").removesuffix("-index")
            recs = self.cc.get((crawl, canonical(q["url"])), [])
            if not recs:
                return httpx.Response(404, text=json.dumps({"message": "No Captures found for: x"}))
            return httpx.Response(200, content=cc_index_lines(recs), headers={"content-type": "text/x-ndjson"})
        if host == "data.commoncrawl.org":
            data = self.warcs.get(parts.path.lstrip("/"))
            rng = request.headers.get("Range", "")
            if data is None or not rng.startswith("bytes="):
                return httpx.Response(404)
            a, b = (int(x) for x in rng[6:].split("-"))
            return httpx.Response(206, content=data[a:b + 1], headers={"Content-Range": f"bytes {a}-{b}/{len(data)}"})
        return httpx.Response(404, text="unknown")

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))
