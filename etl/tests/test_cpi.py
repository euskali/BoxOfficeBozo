"""M5: BLS CPI-U ingest, against a fake BLS API (no network)."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from boffo_etl.fetch import FetchDisabledError, FetchError, Fetcher
from boffo_etl.sources import cpi


def value(month: date) -> float:
    return round(9.8 + (month.year - 1913) * 2 + month.month / 100, 3)


class FakeBLS:
    """Answers v1 POSTs like BLS: monthly values plus an annual average (M13) per full year,
    through ``latest`` (the newest published month)."""

    def __init__(self, latest: date):
        self.latest = latest
        self.requests: list[dict] = []
        self.status = "REQUEST_SUCCEEDED"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and str(request.url) == cpi.API
        q = json.loads(request.content)
        self.requests.append(q)
        if self.status != "REQUEST_SUCCEEDED":
            doc = {"status": self.status, "message": ["daily threshold reached"], "Results": {}}
            return httpx.Response(200, json=doc)
        data = []
        for y in range(int(q["endyear"]), int(q["startyear"]) - 1, -1):
            months = [date(y, m, 1) for m in range(12, 0, -1) if date(y, m, 1) <= self.latest]
            if len(months) == 12:
                data.append({"year": str(y), "period": "M13", "periodName": "Annual", "value": "0"})
            data += [{"year": str(m.year), "period": f"M{m.month:02d}", "value": str(value(m)), "footnotes": [{}]}
                     for m in months]
        doc = {"status": "REQUEST_SUCCEEDED", "message": [],
               "Results": {"series": [{"seriesID": q["seriesid"][0], "data": data}]}}
        return httpx.Response(200, json=doc)


@pytest.fixture
def bls(repo, monkeypatch):
    monkeypatch.setenv("BOFFO_FETCH", "1")
    fake = FakeBLS(date(2026, 10, 1))
    client = httpx.Client(transport=httpx.MockTransport(fake))
    return fake, Fetcher(client, clock=lambda: 0.0, sleep=lambda s: None)


NOV = date(2026, 11, 22)  # a Sunday in ISO week 47


def test_windows_and_finality():
    w = cpi.windows(NOV)
    assert w[0] == (1913, 1922) and w[-1] == (2023, 2026) and len(w) == 12
    assert cpi.is_final((2013, 2022), NOV) and not cpi.is_final((2023, 2026), NOV)
    # December's index comes out in mid-January, so last year's window waits for March.
    assert not cpi.is_final((2017, 2026), date(2027, 2, 10)) and cpi.is_final((2017, 2026), date(2027, 3, 1))
    assert cpi.week_tag(NOV) == "2026-W47"
    assert cpi.request_url((2023, 2026), NOV) == cpi.API + "#2026-W47"
    assert cpi.request_url((2013, 2022), NOV) == cpi.API


def test_first_run_fetches_every_window_once(bls):
    fake, f = bls
    r = cpi.ingest(f, NOV, log=lambda *a: None)
    assert len(fake.requests) == 12
    assert fake.requests[0] == {"seriesid": [cpi.SERIES], "startyear": "1913", "endyear": "1922"}
    t = r.table
    assert t["month"][0] == date(1913, 1, 1) and t["month"][-1] == date(2026, 10, 1)
    assert t.height == (2026 - 1913) * 12 + 10  # every month, no annual averages (M13)
    assert t.filter(t["month"] == date(1982, 6, 1))["cpi"].item() == value(date(1982, 6, 1))
    assert r.report["latest_month"] == "2026-10-01" and r.report["stale_windows"] == []
    assert len(r.report["fetched"]) == 12 and r.report["fetch"] == {"stopped": None}
    # The same week again: everything is cached.
    cpi.ingest(f, NOV, log=lambda *a: None)
    assert len(fake.requests) == 12


def test_a_new_week_asks_only_the_open_window_again(bls):
    fake, f = bls
    cpi.ingest(f, NOV, log=lambda *a: None)
    fake.latest = date(2026, 11, 1)  # November's index is out
    r = cpi.ingest(f, date(2026, 11, 30), log=lambda *a: None)
    assert len(fake.requests) == 13 and fake.requests[-1]["startyear"] == "2023"
    assert r.table["month"][-1] == date(2026, 11, 1)
    assert r.report["pruned_cache_entries"] == 1  # last week's answer to the open window
    assert len(cpi.cached_entries()) == 12


def test_offline_uses_the_newest_cached_answers_and_says_so(bls, monkeypatch):
    fake, f = bls
    cpi.ingest(f, NOV, log=lambda *a: None)
    monkeypatch.delenv("BOFFO_FETCH")
    r = cpi.ingest(f, date(2026, 12, 7), log=lambda *a: None)
    assert len(fake.requests) == 12
    assert r.report["stale_windows"] == ["2023-2026 (2026-W47)"]
    assert r.report["fetch"]["stopped"] == "fetching disabled" and r.report["pruned_cache_entries"] == 0
    assert r.table["month"][-1] == date(2026, 10, 1)


def test_nothing_cached_and_offline_is_fetch_disabled(repo):
    with pytest.raises(FetchDisabledError):
        cpi.ingest(Fetcher(httpx.Client(transport=httpx.MockTransport(lambda r: None))), NOV, log=lambda *a: None)


def test_a_refused_answer_is_not_cached(bls):
    fake, f = bls
    fake.status = "REQUEST_NOT_PROCESSED"  # BLS's daily limit, served as HTTP 200
    with pytest.raises(FetchError, match="could not be fetched"):
        cpi.ingest(f, NOV, log=lambda *a: None)
    assert cpi.cached_entries() == []
    fake.status = "REQUEST_SUCCEEDED"
    cpi.ingest(f, NOV, log=lambda *a: None)
    fake.status = "REQUEST_NOT_PROCESSED"
    r = cpi.ingest(f, date(2026, 11, 30), log=lambda *a: None)  # the open window falls back
    assert r.report["stale_windows"] == ["2023-2026 (2026-W47)"]
    assert r.report["fetch"]["stopped"].startswith("error:")


def test_january_grows_this_years_window_and_drops_the_old_one(bls):
    fake, f = bls
    cpi.ingest(f, NOV, log=lambda *a: None)
    fake.latest = date(2026, 12, 1)
    r = cpi.ingest(f, date(2027, 1, 20), log=lambda *a: None)
    assert fake.requests[-1] == {"seriesid": [cpi.SERIES], "startyear": "2023", "endyear": "2027"}
    assert {e.window for e in cpi.cached_entries()} == set(cpi.windows(date(2027, 1, 20)))
    assert r.table["month"][-1] == date(2026, 12, 1)


def test_run_writes_the_table_and_report(bls, repo):
    fake, f = bls
    out = cpi.run(f, NOV)
    assert out == repo / "data/build/cpi.parquet" and out.is_file()
    report = json.loads((repo / "data/build" / cpi.REPORT).read_text())
    assert report["series"] == "CUUR0000SA0" and report["base"] == "1982-84=100"
