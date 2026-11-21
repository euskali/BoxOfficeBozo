from __future__ import annotations

import json

import httpx
import pytest

from boffo_etl.fetch import (
    BlockedHostError,
    FetchDisabledError,
    FetchError,
    Fetcher,
    HostNotAllowedError,
)

WAYBACK = "https://web.archive.org/web/2020/https://www.boxofficemojo.com/weekend/2020W01/"


class Recorder:
    def __init__(self, handler):
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


def make(handler, **kw):
    rec = Recorder(handler)
    sleeps: list[float] = []
    clock = {"t": 0.0}

    def sleep(s):
        sleeps.append(s)
        clock["t"] += s

    client = httpx.Client(transport=httpx.MockTransport(rec))
    f = Fetcher(client, clock=lambda: clock["t"], sleep=sleep, **kw)
    return f, rec, sleeps


def ok(request):
    return httpx.Response(200, content=b"<html>hi</html>", headers={"content-type": "text/html"})


@pytest.fixture(autouse=True)
def _repo(repo):
    return repo


@pytest.fixture
def fetch_on(monkeypatch):
    monkeypatch.setenv("BOFFO_FETCH", "1")


def test_cached_url_returns_without_network(repo, fetch_on):
    f, rec, sleeps = make(ok)
    p1 = f.fetch(WAYBACK)
    assert len(rec.requests) == 1
    p2 = f.fetch(WAYBACK)
    assert p1 == p2 and len(rec.requests) == 1
    sleeps.clear()
    # Even a brand-new fetcher, with fetching disabled, serves from cache.
    import os
    os.environ.pop("BOFFO_FETCH")
    f2, rec2, sleeps2 = make(ok)
    assert f2.fetch(WAYBACK) == p1
    assert rec2.requests == [] and sleeps2 == []


def test_cache_miss_without_flag_raises(repo):
    f, rec, _ = make(ok)
    with pytest.raises(FetchDisabledError, match="BOFFO_FETCH=1"):
        f.fetch("https://web.archive.org/web/2020/https://example.org/")
    assert rec.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "https://www.boxofficemojo.com/weekend/2020W01/",
        "https://boxofficemojo.com/",
        "https://m.imdb.com/title/tt0000001/",
        "https://datasets.imdbws.com/title.basics.tsv.gz",
        "https://www.the-numbers.com/box-office",
        "https://m.media-imdb.com/x.jpg",
    ],
)
def test_blocked_hosts(url, fetch_on):
    f, rec, _ = make(ok)
    with pytest.raises(BlockedHostError, match="not allowed"):
        f.fetch(url)
    assert rec.requests == []


def test_blocked_host_even_without_flag():
    f, _, _ = make(ok)
    with pytest.raises(BlockedHostError):
        f.fetch("https://www.boxofficemojo.com/")


def test_unlisted_host(fetch_on):
    f, rec, _ = make(ok)
    with pytest.raises(HostNotAllowedError):
        f.fetch("https://example.com/data.csv")
    assert rec.requests == []


def test_lookalike_host_not_treated_as_blocked_subdomain(fetch_on):
    f, _, _ = make(ok)
    with pytest.raises(HostNotAllowedError):  # notimdb.com is not a subdomain of imdb.com
        f.fetch("https://notimdb.com/")


def test_non_http_scheme(fetch_on):
    f, _, _ = make(ok)
    with pytest.raises(FetchError):
        f.fetch("file:///etc/passwd")
    with pytest.raises(FetchError):
        f.fetch("ftp://web.archive.org/x")


def test_wayback_url_allowed_and_cached_with_meta(repo, fetch_on):
    f, rec, _ = make(ok)
    p = f.fetch(WAYBACK)
    assert p.read_bytes() == b"<html>hi</html>"
    assert p.parent == repo / "data" / "raw" / "http" / "web.archive.org"
    assert p.suffix == ".html"
    meta = json.loads((p.parent / (p.name + ".meta.json")).read_text())
    assert meta["url"] == WAYBACK and meta["final_url"] == WAYBACK
    assert meta["status"] == 200 and meta["bytes"] == 15
    assert meta["content_type"] == "text/html" and len(meta["sha256"]) == 64
    assert meta["fetched_at"]
    assert rec.requests[0].headers["user-agent"].startswith("BoxOfficeBozo-ETL/0.1")


def test_suffix_override(fetch_on):
    f, _, _ = make(ok)
    assert f.fetch("https://api.bls.gov/x", suffix=".csv").suffix == ".csv"


def test_redirect_to_blocked_host_rejected_and_not_cached(repo, fetch_on):
    def handler(request):
        if request.url.host == "web.archive.org":
            return httpx.Response(302, headers={"Location": "https://www.boxofficemojo.com/x"})
        return ok(request)

    f, rec, _ = make(handler)
    with pytest.raises(BlockedHostError):
        f.fetch(WAYBACK)
    assert [r.url.host for r in rec.requests] == ["web.archive.org"]
    assert not (repo / "data" / "raw").exists() or not list((repo / "data" / "raw").rglob("*.*"))


def test_redirect_within_allowed_hosts_followed(fetch_on):
    def handler(request):
        if request.url.path == "/a":
            return httpx.Response(301, headers={"Location": "/b"})
        return ok(request)

    f, rec, _ = make(handler)
    p = f.fetch("https://web.archive.org/a")
    meta = json.loads((p.parent / (p.name + ".meta.json")).read_text())
    assert meta["final_url"] == "https://web.archive.org/b"
    assert len(rec.requests) == 2


def test_too_many_redirects(fetch_on):
    f, _, _ = make(lambda r: httpx.Response(302, headers={"Location": "/loop"}), min_interval=0)
    with pytest.raises(FetchError, match="redirects"):
        f.fetch("https://web.archive.org/loop")


def test_503_then_200_retries(fetch_on):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return ok(request)

    f, rec, sleeps = make(handler)
    p = f.fetch("https://web.archive.org/x")
    assert p.exists() and len(rec.requests) == 2
    assert sleeps  # backed off


def test_retry_after_honored(fetch_on):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "30"})
        return ok(request)

    f, _, sleeps = make(handler, min_interval=0)
    f.fetch("https://web.archive.org/x")
    assert 30.0 in sleeps


def test_transport_error_retries_then_gives_up(repo, fetch_on):
    def handler(request):
        raise httpx.ConnectTimeout("boom")

    f, rec, _ = make(handler, min_interval=0)
    with pytest.raises(FetchError, match="4 attempts"):
        f.fetch("https://web.archive.org/x")
    assert len(rec.requests) == 4


def test_per_host_interval_sleeps(fetch_on):
    f, rec, sleeps = make(ok, host_intervals={"web.archive.org": 7.0})
    f.fetch("https://web.archive.org/one")
    assert sleeps == []  # first request to a host does not wait
    f.fetch("https://web.archive.org/two")
    assert sleeps == [7.0]
    f.fetch("https://api.bls.gov/three")  # other host, default interval, no wait
    assert sleeps == [7.0]


def test_default_interval_is_five_seconds(fetch_on):
    f, _, sleeps = make(ok)
    f.fetch("https://web.archive.org/one")
    f.fetch("https://web.archive.org/two")
    assert sleeps == [5.0]


def test_404_raises_without_caching(repo, fetch_on):
    f, rec, _ = make(lambda r: httpx.Response(404, content=b"nope"))
    with pytest.raises(FetchError, match="404"):
        f.fetch("https://web.archive.org/missing")
    assert len(rec.requests) == 1
    raw = repo / "data" / "raw"
    assert not raw.exists() or not [p for p in raw.rglob("*") if p.is_file()]


# --- range requests, accepted statuses, validation (M2) ---------------------

CC_WARC = "https://data.commoncrawl.org/crawl-data/CC-MAIN-2024-10/segments/x/warc/y.warc.gz"


def ranged(request):
    rng = request.headers.get("Range", "")
    assert rng.startswith("bytes=")
    a, b = (int(x) for x in rng[6:].split("-"))
    body = bytes(range(256)) * 4
    return httpx.Response(206, content=body[a:b + 1],
                          headers={"Content-Range": f"bytes {a}-{b}/{len(body)}"})


def test_fetch_range_sends_range_and_caches_by_range(repo, fetch_on):
    f, rec, _ = make(ranged, min_interval=0)
    p = f.fetch_range(CC_WARC, 10, 5)
    assert p.read_bytes() == bytes([10, 11, 12, 13, 14])
    assert rec.requests[0].headers["Range"] == "bytes=10-14"
    assert f.is_cached(CC_WARC, byte_range=(10, 5))
    assert not f.is_cached(CC_WARC, byte_range=(10, 6))
    assert not f.is_cached(CC_WARC)
    f.fetch_range(CC_WARC, 10, 5)
    assert len(rec.requests) == 1  # second call is a cache hit
    f.fetch_range(CC_WARC, 20, 3)
    assert len(rec.requests) == 2  # another range is another entry
    meta = json.loads(p.with_name(p.name + ".meta.json").read_text())
    assert meta["range"] == [10, 14] and meta["status"] == 206


def test_fetch_range_refuses_a_whole_file_answer(repo, fetch_on):
    f, _, _ = make(lambda r: httpx.Response(200, content=b"x" * 5000), min_interval=0)
    with pytest.raises(FetchError, match="HTTP 200"):
        f.fetch_range(CC_WARC, 0, 10)
    assert not f.is_cached(CC_WARC, byte_range=(0, 10))


def test_fetch_range_checks_content_range(repo, fetch_on):
    f, _, _ = make(lambda r: httpx.Response(206, content=b"abcde", headers={"Content-Range": "bytes 0-4/99"}),
                   min_interval=0)
    with pytest.raises(FetchError, match="Content-Range|answered"):
        f.fetch_range(CC_WARC, 10, 5)


def test_fetch_range_offline_raises(repo):
    f, rec, _ = make(ranged)
    with pytest.raises(FetchDisabledError):
        f.fetch_range(CC_WARC, 0, 4)
    assert rec.requests == []


def test_fetch_range_policy_applies(fetch_on):
    f, _, _ = make(ranged)
    with pytest.raises(BlockedHostError):
        f.fetch_range("https://www.boxofficemojo.com/weekend/2020W01/", 0, 4)


def test_accept_status_caches_a_404_body(repo, fetch_on):
    url = "https://index.commoncrawl.org/CC-MAIN-2024-10-index?url=x&output=json"
    f, rec, _ = make(lambda r: httpx.Response(404, content=b'{"message": "No Captures found"}'), min_interval=0)
    p = f.fetch(url, accept_status=(200, 404))
    assert b"No Captures" in p.read_bytes()
    assert json.loads(p.with_name(p.name + ".meta.json").read_text())["status"] == 404
    f.fetch(url, accept_status=(200, 404))
    assert len(rec.requests) == 1


def test_validate_refusal_is_not_cached(repo, fetch_on):
    def must_be_json(body):
        json.loads(body)

    f, rec, _ = make(ok, min_interval=0)
    with pytest.raises(FetchError, match="unusable body"):
        f.fetch("https://web.archive.org/cdx/search/cdx?url=x", validate=must_be_json)
    assert not f.is_cached("https://web.archive.org/cdx/search/cdx?url=x")


def test_network_requests_counts_only_real_requests(repo, fetch_on):
    f, _, _ = make(ok, min_interval=0)
    f.fetch("https://web.archive.org/a")
    f.fetch("https://web.archive.org/a")
    assert f.network_requests == 1


def test_retry_delays_back_off(fetch_on):
    f, _, sleeps = make(lambda r: httpx.Response(503), min_interval=0)
    with pytest.raises(FetchError, match="4 attempts"):
        f.fetch("https://web.archive.org/down")
    assert sleeps == [10.0, 30.0, 90.0]


def test_reduce_caches_only_what_is_kept(repo, fetch_on):
    big = json.dumps({"keep": [1, 2], "drop": "x" * 5000}).encode()
    f, rec, _ = make(lambda r: httpx.Response(200, content=big, headers={"content-type": "application/json"}))
    url = "https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q1"
    kept = lambda body: json.dumps({"keep": json.loads(body)["keep"]}).encode()  # noqa: E731
    path = f.fetch(url, validate=lambda b: json.loads(b), reduce=kept)
    assert json.loads(path.read_bytes()) == {"keep": [1, 2]}
    meta = json.loads(path.with_name(path.name + ".meta.json").read_text())
    assert meta["reduced"] is True and meta["original_bytes"] == len(big) and meta["bytes"] == path.stat().st_size
    assert f.fetch(url, reduce=kept) == path and len(rec.requests) == 1  # cached: never fetched again
