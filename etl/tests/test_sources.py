"""The site's list of sources (site/src/sources.json, shown on the About page and in the footer)
matches what the build uses: the fetch allowlist, the citations in data/manual/*.csv, and the
sections of DATA_NOTICE.md. Adding a source means updating all of them together."""

from __future__ import annotations

import csv
import json
import re
from urllib.parse import urlsplit

import pytest

from boffo_etl.fetch import ALLOWLIST, DENYLIST
from boffo_etl.manual import SCHEMAS

from conftest import REAL_REPO_ROOT

SOURCES = json.loads((REAL_REPO_ROOT / "site" / "src" / "sources.json").read_text(encoding="utf-8"))["sources"]
NOTICE = (REAL_REPO_ROOT / "DATA_NOTICE.md").read_text(encoding="utf-8")


def notice_sections() -> dict[str, str]:
    """DATA_NOTICE.md's "Sources and their terms": {### heading: its text}."""
    body = NOTICE.split("\n## Sources and their terms\n", 1)[1].split("\n## ", 1)[0]
    parts = re.split(r"^### (.+)$", body, flags=re.M)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts), 2)}


def manual_citations() -> list[tuple[str, str, str]]:
    """(file, source, source_url) for every row of every hand-curated CSV."""
    out = []
    for name in SCHEMAS:
        with (REAL_REPO_ROOT / "data" / "manual" / name).open(newline="", encoding="utf-8") as fh:
            out += [(name, r["source"], r.get("source_url") or "") for r in csv.DictReader(fh)]
    return out


def test_the_sources_have_what_the_site_shows():
    assert len({s["id"] for s in SOURCES}) == len(SOURCES)
    for s in SOURCES:
        assert s["name"] in s["label"]
        assert s["url"].startswith("https://")
        assert s["terms"] and s["gives"].endswith(".")


def test_data_notice_has_a_section_for_every_source_and_no_other():
    assert set(notice_sections()) == {s["notice"] for s in SOURCES}


@pytest.mark.parametrize("source", SOURCES, ids=[s["id"] for s in SOURCES])
def test_data_notice_names_each_source_in_its_section(source):
    assert source["name"] in source["notice"] + notice_sections()[source["notice"]]


def test_every_fetched_host_belongs_to_exactly_one_source():
    hosts = [h for s in SOURCES for h in s["hosts"]]
    assert len(hosts) == len(set(hosts))
    assert sorted(hosts) == sorted(ALLOWLIST)
    assert not any(h == bad or h.endswith("." + bad) for h in hosts for bad in DENYLIST)


def test_every_hand_curated_row_cites_a_listed_source():
    rows = manual_citations()
    assert rows, "data/manual has no rows to check"
    for file, source, url in rows:
        owners = [s for s in SOURCES if any(source.startswith(p) for p in s["cited_as"])]
        assert len(owners) == 1, f"{file}: {source[:80]!r} cites no listed source (or several)"
        if url:
            assert urlsplit(url).hostname in owners[0]["citation_hosts"], f"{file}: {url} isn't a host {owners[0]['id']} is cited from"


def test_every_cited_source_is_still_cited():
    rows = manual_citations()
    for s in SOURCES:
        for prefix in s["cited_as"]:
            assert any(src.startswith(prefix) for _, src, _ in rows), f"{s['id']}: nothing in data/manual cites {prefix!r}"
