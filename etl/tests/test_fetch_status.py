from __future__ import annotations

import csv
import json

import pytest

from boffo_etl import fetch_status, paths
from boffo_etl.sources import bom_weekend


def _weekends(build, statuses):
    with (build / fetch_status.WEEKENDS_CSV).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(bom_weekend.WEEKEND_COLUMNS)
        for i, status in enumerate(statuses, 1):
            w.writerow([f"2026W{i:02d}", "2026-01-04", status, "", "", "", 0, 0, "false", ""])


def _write(build, name, report):
    (build / name).write_text(json.dumps(report), encoding="utf-8")


@pytest.fixture
def done(repo):
    """data/build/ as a finished build leaves it."""
    build = paths.data_build()
    build.mkdir(parents=True)
    _weekends(build, ["ok", "ok", "no_capture", "empty_chart"])
    _write(build, "bom_weekend_report.json", {"statuses": {"ok": 2}})
    _write(build, "wikidata_report.json", {"snapshot": "2026-11", "stale_reason": None,
                                           "release_page_tt_lookup": {"asked": 3, "found": 1, "error": None}})
    _write(build, "cpi_report.json", {"fetch": {"stopped": None}})
    _write(build, "credits_report.json", {"month": "2026-11", "month_complete": True, "films": 10,
                                          "films_with_statements": 10, "fetch": {"stopped": None}})
    return build


def test_a_finished_build_is_complete(done):
    assert fetch_status.unfinished() == []


def test_pending_and_failed_weekends_are_unfinished(done):
    _weekends(done, ["ok", "pending", "pending", "error", "unchecked", "no_capture"])
    [reason] = fetch_status.unfinished()
    assert reason == ("weekend charts: 4 weekends not fetched yet (1 error, 2 pending, 1 unchecked), "
                      "first 2026W02")


def test_a_credits_month_cut_short_is_unfinished(done):
    _write(done, "credits_report.json", {"month": "2026-11", "month_complete": False, "films": 10,
                                         "films_with_statements": 4, "fetch": {"stopped": "time budget"}})
    assert fetch_status.unfinished() == ["credits: month 2026-11 has statements for 4 of 10 films (time budget)"]


def test_stand_ins_and_failed_lookups_are_unfinished(done):
    _write(done, "wikidata_report.json", {"snapshot": "2026-10", "stale_reason": "HTTP 503",
                                          "release_page_tt_lookup": {"error": "timed out"}})
    _write(done, "cpi_report.json", {"fetch": {"stopped": "error: HTTP 429"}})
    assert fetch_status.unfinished() == [
        "wikidata: this month's snapshot couldn't be fetched, 2026-10 stood in (HTTP 503)",
        "wikidata: the IMDb id lookup failed (timed out)",
        "cpi: stopped fetching (error: HTTP 429)",
    ]


def test_a_step_that_didnt_run_is_unfinished(done):
    (done / fetch_status.WEEKENDS_CSV).unlink()
    (done / "cpi_report.json").unlink()
    assert fetch_status.unfinished() == [
        "no bom_weekend_weekends.csv: the weekend charts step didn't run",
        "no cpi_report.json: that step didn't run",
    ]


def test_main_writes_the_github_output(done, tmp_path, monkeypatch, capsys):
    out = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert fetch_status.main([]) == 0
    assert "complete, nothing left" in capsys.readouterr().out
    _weekends(done, ["pending"])
    assert fetch_status.main([]) == 0  # unfinished isn't an error
    assert "weekend charts: 1 weekend not fetched yet (1 pending), first 2026W01" in capsys.readouterr().out
    assert out.read_text(encoding="utf-8") == "complete=true\ncomplete=false\n"
