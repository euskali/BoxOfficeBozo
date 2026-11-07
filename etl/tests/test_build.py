from __future__ import annotations

import json
from datetime import datetime

import polars as pl

from boffo_etl import build
from boffo_etl.fetch import Fetcher
from boffo_etl.sources import stat695
from boffo_etl.sources.stat695 import git_blob_sha1

from test_stat695 import write_fixture_rda


def test_build_creates_dirs_and_manifest(repo, capsys):
    assert build.main([]) == 0
    for d in ("data/raw", "data/build", "site/public/data"):
        assert (repo / d).is_dir()
    m = json.loads((repo / "site/public/data/manifest.json").read_text())
    assert m["schema_version"] == 1
    assert m["tables"] == []
    assert m["git_sha"] is None
    datetime.fromisoformat(m["built_at"])
    out = capsys.readouterr().out
    assert "disabled" in out
    assert "step stat695: skipped, its raw input is not cached" in out
    assert "step bom_weekend: skipped, its raw input is not cached" in out
    assert "step wikidata: skipped, its raw input is not cached" in out
    assert "not implemented until M5" in out


def test_build_fails_when_data_is_required(repo, monkeypatch, capsys):
    monkeypatch.setenv("BOFFO_REQUIRE_DATA", "1")
    assert build.main([]) == 1
    assert "FAILED" in capsys.readouterr().err


def test_build_records_git_sha_and_fetch_flag(repo, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("BOFFO_FETCH", "1")
    monkeypatch.setattr(build, "STEPS", [("stat695", "M1", lambda: None)])  # never touch the network
    assert build.main([]) == 0
    assert json.loads((repo / "site/public/data/manifest.json").read_text())["git_sha"] == "abc123"
    assert "ENABLED" in capsys.readouterr().out


def test_build_aborts_on_manual_errors(repo, capsys):
    (repo / "data/manual/ticket_prices.csv").write_text("bad,header\n", encoding="utf-8")
    assert build.main([]) == 1
    assert not (repo / "site/public/data/manifest.json").exists()


def test_full_build_from_cached_rda(repo, monkeypatch, capsys):
    """Offline build from a synthetic mojo.rda already in the raw cache."""
    directory, digest = Fetcher._stem(stat695.URL)
    directory.mkdir(parents=True)
    path = write_fixture_rda(directory / f"{digest}.rda")
    monkeypatch.setattr(stat695, "BLOB_SHA1", git_blob_sha1(path.read_bytes()))

    assert build.main([]) == 0
    out = capsys.readouterr().out
    assert "stat695: 4 source rows -> 4 snapshots" in out
    assert "published snapshots.parquet: 4 rows" in out

    site = repo / "site/public/data"
    snaps = pl.read_parquet(site / "snapshots.parquet")
    assert snaps.height == 4 and set(snaps["source"]) == {"stat695"}
    assert pl.read_parquet(site / "releases.parquet").height == 2
    tables = {t["name"]: t for t in json.loads((site / "manifest.json").read_text())["tables"]}
    assert set(tables) == {"snapshots", "releases", "titles"}
    assert tables["snapshots"]["rows"] == 4 and len(tables["snapshots"]["sha256"]) == 64
    # No Wikidata snapshot offline: every release keeps its provisional id, and says so.
    rels = pl.read_parquet(site / "releases.parquet")
    assert set(rels["match_method"]) == {"unmatched"} and all(t.startswith("bb_") for t in rels["title_id"])
    assert sorted(pl.read_parquet(site / "titles.parquet")["title_id"]) == sorted(set(rels["title_id"]))
    for f in ("stat695_snapshots.parquet", "stat695_releases.parquet", "stat695_report.json", "stat695_rereleases.csv",
              "match.parquet", "match_report.csv", "match_report.json"):
        assert (repo / "data/build" / f).is_file()


def test_assemble_releases_recounts_stitched_releases():
    from datetime import date

    blank = {k: None for k in stat695.RELEASE_SCHEMA}
    rel = pl.DataFrame([{**blank, **r} for r in [
        {"release_id": "legacy:a", "source": "stat695", "source_key": "a", "first_weekend": date(2016, 12, 4),
         "last_weekend": date(2017, 1, 1), "weekends": 5},
        {"release_id": "bom:rl9", "source": "bom_weekend", "source_key": "rl9", "first_weekend": date(2017, 1, 8),
         "last_weekend": date(2017, 1, 8), "weekends": 1},
        {"release_id": "legacy:gone", "source": "stat695", "source_key": "gone", "first_weekend": date(2001, 1, 7),
         "last_weekend": date(2001, 1, 7), "weekends": 1},
        {"release_id": "legacy:fresh2017", "source": "bom_weekend", "source_key": "fresh2017",
         "first_weekend": date(2017, 1, 29), "last_weekend": date(2017, 1, 29), "weekends": 1},
    ]], schema=stat695.RELEASE_SCHEMA)
    snaps = pl.DataFrame({
        "release_id": ["legacy:a"] * 3 + ["bom:rl9"],
        "weekend_end": [date(2016, 12, 4), date(2017, 1, 1), date(2017, 1, 15), date(2017, 1, 8)],
    })
    links = pl.DataFrame({"release_id": ["legacy:a"], "bom_release_id": ["rl1"]})
    out = {r["release_id"]: r for r in build.assemble_releases(rel, snaps, links).to_dicts()}
    assert set(build.assemble_releases(rel, snaps, links).columns) == set(build.PUBLISHED_RELEASE_SCHEMA)
    assert (out["legacy:a"]["bom_release_id"], out["legacy:a"]["last_weekend"], out["legacy:a"]["weekends"]) == (
        "rl1", date(2017, 1, 15), 3)
    assert out["bom:rl9"]["bom_release_id"] == "rl9"
    assert out["legacy:gone"]["bom_release_id"] is None and out["legacy:gone"]["weekends"] == 1
    assert out["legacy:fresh2017"]["bom_release_id"] is None  # an old-style page's legacy id isn't an rl id
