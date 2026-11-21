"""Cached, polite, host-gated HTTP fetcher.

Rules (see docs/DATA_SOURCES.md):

* Offline by default. The network is touched only when ``BOFFO_FETCH=1``
  (set by the CI data-build job). A cache miss otherwise raises
  :class:`FetchDisabledError`.
* Live Box Office Mojo / IMDb / The Numbers fetching is never allowed. Use
  the Wayback Machine or Common Crawl instead.
* Only allow-listed hosts may be contacted; every redirect hop is re-checked.
* A cached URL is never re-fetched.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx

from . import paths

USER_AGENT = (
    "BoxOfficeBozo-ETL/0.1 (+https://github.com/euskali/BoxOfficeBozo; "
    "non-commercial hobby project)"
)

# Hosts (and all their subdomains) that must never be fetched live.
DENYLIST: tuple[str, ...] = (
    "boxofficemojo.com",
    "imdb.com",
    "imdbws.com",
    "media-imdb.com",
    "the-numbers.com",
)

# Exact hosts that may be fetched.
ALLOWLIST: tuple[str, ...] = (
    "web.archive.org",
    "archive.org",
    "index.commoncrawl.org",
    "data.commoncrawl.org",
    "query.wikidata.org",
    "www.wikidata.org",
    "qlever.cs.uni-freiburg.de",
    "qlever.dev",
    "download.bls.gov",
    "api.bls.gov",
    "github.com",
    "raw.githubusercontent.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
)

DEFAULT_MIN_INTERVAL = 5.0
MAX_REDIRECTS = 5
MAX_ATTEMPTS = 4
RETRY_DELAYS = (10.0, 30.0, 90.0)  # seconds before attempts 2, 3 and 4 (busy archives recover slowly)
MAX_BODY_BYTES = 200 * 1024 * 1024  # a whole-file download larger than this is refused
ENV_FLAG = "BOFFO_FETCH"


class FetchError(Exception):
    """Base class for fetch failures."""


class FetchDisabledError(FetchError):
    """Not cached and network fetching is disabled."""


class BlockedHostError(FetchError):
    """Host is on the permanent denylist."""


class HostNotAllowedError(FetchError):
    """Host is not on the allowlist."""


def _hostname(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def check_url_policy(url: str) -> str:
    """Validate scheme and host. Returns the host. Raises on violation."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchError(f"{url} has unsupported scheme {parts.scheme!r}; only http/https allowed")
    host = _hostname(url)
    if not host:
        raise FetchError(f"{url} has no host")
    for bad in DENYLIST:
        if host == bad or host.endswith("." + bad):
            raise BlockedHostError(
                f"live fetching from {host} is not allowed; use the Wayback Machine "
                "or Common Crawl (see docs/DATA_SOURCES.md)"
            )
    if host not in ALLOWLIST:
        raise HostNotAllowedError(
            f"host {host} is not on the fetch allowlist (boffo_etl.fetch.ALLOWLIST)"
        )
    return host


def _guess_ext(content_type: str | None) -> str:
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        known = {
            "application/json": ".json",
            "application/sparql-results+json": ".json",
            "text/csv": ".csv",
            "text/html": ".html",
            "application/gzip": ".gz",
            "application/x-gzip": ".gz",
            "text/plain": ".txt",
        }
        if ct in known:
            return known[ct]
        guessed = mimetypes.guess_extension(ct)
        if guessed:
            return guessed
    return ".bin"


def _range_key(url: str, start: int, length: int) -> str:
    return f"{url}#bytes={start}-{start + length - 1}"


class Fetcher:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        host_intervals: dict[str, float] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self.min_interval = min_interval
        self.host_intervals = dict(host_intervals or {})
        self._clock = clock
        self._sleep = sleep
        self._last_request: dict[str, float] = {}
        self.network_requests = 0  # requests actually sent (cache hits don't count)

    # -- cache -----------------------------------------------------------
    @staticmethod
    def _stem(key: str) -> tuple[Path, str]:
        host = _hostname(key) or "unknown"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        return paths.data_raw() / "http" / host, digest

    def _find_cached(self, key: str) -> Path | None:
        directory, digest = self._stem(key)
        if not directory.is_dir():
            return None
        for p in sorted(directory.glob(digest + "*")):
            if p.name.endswith(".meta.json") or p.name.endswith(".tmp"):
                continue
            if p.name == digest or p.name.startswith(digest + "."):
                return p
        return None

    def is_cached(self, url: str, *, byte_range: tuple[int, int] | None = None) -> bool:
        """True if ``url`` (or that byte range of it) is already in data/raw/."""
        check_url_policy(url)
        key = _range_key(url, *byte_range) if byte_range else url
        return self._find_cached(key) is not None

    # -- politeness ------------------------------------------------------
    def _wait_turn(self, host: str) -> None:
        interval = self.host_intervals.get(host, self.min_interval)
        last = self._last_request.get(host)
        if last is not None:
            remaining = interval - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request[host] = self._clock()

    # -- network ---------------------------------------------------------
    def _get_client(self) -> tuple[httpx.Client, bool]:
        if self._client is not None:
            return self._client, False
        return httpx.Client(timeout=60.0, headers={"User-Agent": USER_AGENT}), True

    def _request_once(self, client: httpx.Client, url: str, headers: dict[str, str]) -> httpx.Response:
        host = check_url_policy(url)
        self._wait_turn(host)
        self.network_requests += 1
        request = client.build_request("GET", url, headers={"User-Agent": USER_AGENT, **headers})
        # Streamed, so a server that ignores a Range header can't make us read a whole file.
        return client.send(request, follow_redirects=False, stream=True)

    def _request_with_retries(self, client: httpx.Client, url: str, headers: dict[str, str]) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = self._request_once(client, url, headers)
            except httpx.TransportError as exc:  # includes timeouts
                last_exc = exc
                if attempt == MAX_ATTEMPTS:
                    break
                self._sleep(RETRY_DELAYS[attempt - 1])
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                resp.close()
                last_exc = FetchError(f"{url} returned HTTP {resp.status_code}")
                if attempt == MAX_ATTEMPTS:
                    break
                delay = RETRY_DELAYS[attempt - 1]
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        pass
                self._sleep(delay)
                continue
            return resp
        raise FetchError(f"{url} failed after {MAX_ATTEMPTS} attempts: {last_exc}")

    @staticmethod
    def _read(resp: httpx.Response, limit: int) -> bytes:
        chunks: list[bytes] = []
        size = 0
        try:
            for chunk in resp.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise FetchError(f"{resp.request.url} is larger than {limit} bytes; refusing to read it")
                chunks.append(chunk)
        finally:
            resp.close()
        return b"".join(chunks)

    def _download(
        self, url: str, *, headers: dict[str, str], accept: tuple[int, ...], limit: int
    ) -> tuple[httpx.Response, bytes, str]:
        client, owned = self._get_client()
        try:
            current = url
            for _ in range(MAX_REDIRECTS + 1):
                resp = self._request_with_retries(client, current, headers)
                if resp.is_redirect:
                    resp.close()
                    location = resp.headers.get("Location")
                    if not location:
                        raise FetchError(f"{current} redirected without a Location header")
                    current = urljoin(current, location)
                    check_url_policy(current)  # reject before spending a request
                    continue
                if resp.status_code not in accept:
                    resp.close()
                    raise FetchError(f"{current} returned HTTP {resp.status_code}")
                return resp, self._read(resp, limit), current
            raise FetchError(f"{url} exceeded {MAX_REDIRECTS} redirects")
        finally:
            if owned:
                client.close()

    def _store(self, key: str, url: str, resp: httpx.Response, body: bytes, final_url: str,
               suffix: str | None, extra: dict) -> Path:
        content_type = resp.headers.get("content-type")
        directory, digest = self._stem(key)
        directory.mkdir(parents=True, exist_ok=True)
        ext = suffix if suffix is not None else _guess_ext(content_type)
        if ext and not ext.startswith("."):
            ext = "." + ext
        target = directory / (digest + ext)
        meta = {
            "url": url,
            **extra,
            "final_url": final_url,
            "status": resp.status_code,
            "content_type": content_type,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        # Meta first, body last: the body's existence marks a complete cache entry.
        self._atomic_write(directory / (target.name + ".meta.json"), json.dumps(meta, indent=2).encode())
        self._atomic_write(target, body)
        return target

    @staticmethod
    def _require_network(what: str) -> None:
        if os.environ.get(ENV_FLAG) != "1":
            raise FetchDisabledError(
                f"{what} is not cached in data/raw/. Network fetching runs in the CI "
                f"data-build job; set {ENV_FLAG}=1 to allow it."
            )

    # -- public ----------------------------------------------------------
    def fetch(
        self,
        url: str,
        *,
        suffix: str | None = None,
        accept_status: tuple[int, ...] = (200,),
        validate: Callable[[bytes], None] | None = None,
        reduce: Callable[[bytes], bytes] | None = None,
    ) -> Path:
        """Return the cached body of ``url``, downloading it first if needed (CI only).

        ``accept_status`` lists the final HTTP statuses whose body is worth
        caching (an index's "no captures" 404, say). ``validate`` may raise to
        refuse a body, which then isn't cached (an outage page served as 200).
        ``reduce`` turns a validated body into the part worth keeping, which is
        what gets cached (the meta file records the original's size and hash):
        for answers far bigger than what's used, like Wikidata's every claim of
        a film when only its credits are read.
        """
        check_url_policy(url)  # policy first, even for cached URLs
        cached = self._find_cached(url)
        if cached is not None:
            return cached
        self._require_network(url)
        resp, body, final_url = self._download(url, headers={}, accept=accept_status, limit=MAX_BODY_BYTES)
        if validate is not None:
            try:
                validate(body)
            except Exception as exc:  # an outage page served as 200, say: don't cache it
                raise FetchError(f"{url} returned an unusable body: {exc}") from exc
        extra: dict = {}
        if reduce is not None:
            extra = {"reduced": True, "original_bytes": len(body),
                     "original_sha256": hashlib.sha256(body).hexdigest()}
            body = reduce(body)
        return self._store(url, url, resp, body, final_url, suffix, extra)

    def fetch_range(self, url: str, start: int, length: int, *, suffix: str | None = ".bin") -> Path:
        """Fetch ``length`` bytes of ``url`` from ``start`` (one WARC record, say), cached by range."""
        if start < 0 or length <= 0:
            raise FetchError(f"bad byte range {start}+{length} for {url}")
        check_url_policy(url)
        key = _range_key(url, start, length)
        cached = self._find_cached(key)
        if cached is not None:
            return cached
        self._require_network(key)
        end = start + length - 1
        resp, body, final_url = self._download(
            url, headers={"Range": f"bytes={start}-{end}"}, accept=(206,), limit=length + 1024
        )
        content_range = resp.headers.get("Content-Range", "")
        if not content_range.startswith(f"bytes {start}-{end}/") or len(body) != length:
            raise FetchError(f"{url} answered Range {start}-{end} with {content_range!r} ({len(body)} bytes)")
        return self._store(key, url, resp, body, final_url, suffix, {"range": [start, end]})

    @staticmethod
    def _atomic_write(dest: Path, data: bytes) -> None:
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=dest.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, dest)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


default_fetcher = Fetcher()


def fetch(url: str, *, suffix: str | None = None) -> Path:
    """Fetch ``url`` via the module-level default :class:`Fetcher`."""
    return default_fetcher.fetch(url, suffix=suffix)
