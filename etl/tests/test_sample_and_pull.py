"""M7: make sample-data (fictional local data) and make pull-data (the published tables)."""

from __future__ import annotations

import hashlib
import json

import httpx
import polars as pl
import pytest

from boffo_etl import checks, paths, pull_data, queries, sample
from boffo_etl.build import RELEASES_OUT_SCHEMA
from boffo_etl.cume import CUME_SCHEMA
from boffo_etl.match import TITLE_SCHEMA
from boffo_etl.sources.credits import CREDITS_SCHEMA, PEOPLE_SCHEMA
from boffo_etl.sources.stat695 import SNAPSHOT_SCHEMA

SCHEMAS = {"snapshots": SNAPSHOT_SCHEMA, "releases": RELEASES_OUT_SCHEMA, "titles": TITLE_SCHEMA,
           "credits": CREDITS_SCHEMA, "people": PEOPLE_SCHEMA, "title_cume": CUME_SCHEMA}


# --- sample-data -------------------------------------------------------------------------

def test_sample_data_has_the_real_schemas_and_is_marked(repo):
    assert sample.main([]) == 0
    out = paths.site_data()
    for name, schema in SCHEMAS.items():
        assert dict(pl.read_parquet_schema(out / f"{name}.parquet")) == schema, name
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sample"] is True
    assert {t["name"] for t in manifest["tables"]} >= set(queries.TABLES)
    assert sample.is_sample_data()


def test_sample_titles_and_names_are_obviously_fictional(repo):
    sample.write()
    titles = pl.read_parquet(paths.site_data() / "titles.parquet")
    assert titles["title"].str.starts_with("Sample: ").all()
    assert titles["title_id"].str.starts_with("sample_").all()
    people = pl.read_parquet(paths.site_data() / "people.parquet")
    assert people["person_id"].str.starts_with("sample_").all()


def test_sample_totals_add_up_and_the_site_queries_run(repo):
    sample.write()
    con = queries.connect(paths.site_data())
    latest = queries.latest_date(con)
    top = queries.leaderboard(con, latest, "nominal", limit=5)
    assert len(top) == 5 and [r["rank"] for r in top] == [1, 2, 3, 4, 5]
    # a title's nominal total is its baseline plus each release's last charted total
    for r in top:
        releases = queries.film_releases(con, r["title_id"])
        assert r["cume_nominal"] == sum(x["total_gross"] for x in releases)
    old = queries.film(con, "sample_old1")
    assert (old["baseline"], old["baseline_is_rental"], old["cume_nominal"]) == (True, True, 40_000_000)
    assert queries.weekend_chart(con, latest)[0]["rank"] == 1
    assert queries.person_totals(con, latest, "actor", "admissions", limit=1)[0]["rank"] == 1


def test_sample_data_never_replaces_real_data_unasked(repo):
    out = paths.site_data()
    out.mkdir(parents=True)
    (out / "manifest.json").write_text(json.dumps({"tables": []}), encoding="utf-8")
    assert sample.main([]) == 1
    assert not (out / "titles.parquet").exists()
    assert sample.main(["--force"]) == 0
    assert sample.is_sample_data()


def test_checks_fail_on_sample_data(repo):
    sample.write()
    issues = checks.check_sample_data()
    assert [i.severity for i in issues] == ["error"]
    assert "sample" in issues[0].message


# --- pull-data ---------------------------------------------------------------------------

def _site(files: dict[str, bytes], manifest: dict | None = None):
    seen = []
    tables = [{"name": n.removesuffix(".parquet"), "file": n, "rows": 1, "bytes": len(b),
               "sha256": hashlib.sha256(b).hexdigest()} for n, b in files.items()]
    body = json.dumps(manifest if manifest is not None else {"schema_version": 1, "tables": tables}).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        name = request.url.path.rsplit("/", 1)[-1]
        if name == "manifest.json":
            return httpx.Response(200, content=body)
        if name in files:
            return httpx.Response(200, content=files[name])
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_pull_data_copies_the_published_tables(repo):
    client, seen = _site({"titles.parquet": b"PAR1 titles", "cpi.parquet": b"PAR1 cpi"})
    tables = pull_data.pull(client)
    assert [t["file"] for t in tables] == ["titles.parquet", "cpi.parquet"]
    assert (paths.site_data() / "titles.parquet").read_bytes() == b"PAR1 titles"
    assert json.loads((paths.site_data() / "manifest.json").read_text())["tables"] == tables
    assert seen == ["https://boxofficebozo.com/data/manifest.json", "https://boxofficebozo.com/data/titles.parquet",
                    "https://boxofficebozo.com/data/cpi.parquet"]


def test_pull_data_rejects_a_checksum_mismatch_and_writes_nothing(repo):
    good = b"PAR1 titles"
    manifest = {"tables": [{"name": "titles", "file": "titles.parquet", "rows": 1, "bytes": len(good),
                            "sha256": hashlib.sha256(b"something else").hexdigest()}]}
    client, _ = _site({"titles.parquet": good}, manifest)
    with pytest.raises(pull_data.PullError, match="checksum"):
        pull_data.pull(client)
    assert not (paths.site_data() / "titles.parquet").exists()


def test_pull_data_refuses_odd_file_names_and_denied_hosts(repo, monkeypatch):
    client, _ = _site({}, {"tables": [{"name": "x", "file": "../x.parquet", "rows": 1, "bytes": 1, "sha256": "0"}]})
    with pytest.raises(pull_data.PullError, match="unexpected file name"):
        pull_data.pull(client)
    monkeypatch.setenv(pull_data.SITE_URL_FLAG, "https://www.boxofficemojo.com/")
    with pytest.raises(pull_data.PullError, match="denylist"):
        pull_data.pull(client)
