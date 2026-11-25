"""Is the fetching done? Read after ``make etl`` in CI, to decide whether another pass should continue it.

A data-build job can't fetch everything from an empty raw-download cache: the first full run of
the weekend charts alone took 270 minutes of a 330-minute job, before Wikidata and the credits.
Each step stops at its time budget and caches what it got, so ``deploy.yml`` chains passes: a
pass whose fetching isn't done saves the cache and hands over to the next one, which picks up
from there. This module reads the build's own reports in ``data/build/`` and says whether
anything is left that another pass could fetch:

* weekend charts still pending, or whose archive lookup failed or couldn't be checked;
* a Wikidata snapshot or credits month that couldn't be fetched in full (an older one stood in);
* BLS CPI windows that couldn't be refreshed;
* a missing report (the step didn't run).

Archived release pages aren't on the list: they are fetched a batch per run by design, so
there are nearly always some left, and the site is complete without them.

Run with ``python -m boffo_etl.fetch_status``. It prints what's left, and when ``GITHUB_OUTPUT``
is set it writes ``complete=true`` or ``complete=false`` there for the workflow. It exits 0 either
way: an unfinished fetch isn't an error.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

from . import paths
from .sources import bom_weekend

WEEKENDS_CSV = "bom_weekend_weekends.csv"
REPORTS = ("bom_weekend_report.json", "wikidata_report.json", "cpi_report.json", "credits_report.json")
# Weekend statuses that another run can still turn into a chart or an explained gap.
UNFINISHED_WEEKENDS = (bom_weekend.PENDING, bom_weekend.ERROR, bom_weekend.UNCHECKED)


def _report(build_dir: Path, name: str) -> dict | None:
    path = build_dir / name
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _weekends(build_dir: Path) -> list[str]:
    path = build_dir / WEEKENDS_CSV
    if not path.is_file():
        return [f"no {WEEKENDS_CSV}: the weekend charts step didn't run"]
    with path.open(newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["status"] in UNFINISHED_WEEKENDS]
    if not rows:
        return []
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    detail = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
    return [f"weekend charts: {len(rows)} weekend{'' if len(rows) == 1 else 's'} not fetched yet ({detail}), "
            f"first {rows[0]['code']}"]


def unfinished(build_dir: Path | None = None) -> list[str]:
    """What another pass could still fetch, one line per source. Empty when the fetching is done."""
    build_dir = build_dir or paths.data_build()
    reasons = _weekends(build_dir)
    for name in REPORTS:
        if _report(build_dir, name) is None:
            reasons.append(f"no {name}: that step didn't run")

    wd = _report(build_dir, "wikidata_report.json")
    if wd:
        if wd.get("stale_reason"):
            reasons.append(f"wikidata: this month's snapshot couldn't be fetched, {wd['snapshot']} stood in "
                           f"({wd['stale_reason']})"[:300])
        if (wd.get("release_page_tt_lookup") or {}).get("error"):
            reasons.append(f"wikidata: the IMDb id lookup failed ({wd['release_page_tt_lookup']['error']})"[:300])

    cpi = _report(build_dir, "cpi_report.json")
    if cpi and (cpi.get("fetch") or {}).get("stopped"):
        reasons.append(f"cpi: stopped fetching ({cpi['fetch']['stopped']})"[:300])

    cr = _report(build_dir, "credits_report.json")
    if cr and not cr.get("month_complete", False):
        stopped = (cr.get("fetch") or {}).get("stopped") or "not every film fetched"
        reasons.append(f"credits: month {cr.get('month')} has statements for {cr.get('films_with_statements')} "
                       f"of {cr.get('films')} films ({stopped})"[:300])
    return reasons


def main(argv: list[str] | None = None) -> int:
    reasons = unfinished()
    complete = not reasons
    if complete:
        print("fetch status: complete, nothing left for another pass to fetch")
    else:
        print("fetch status: unfinished, another pass can fetch:")
        for r in reasons:
            print(f"  {r}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"complete={'true' if complete else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
