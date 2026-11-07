"""Synthetic Box Office Mojo pages and archive answers for tests.

Hand-written to mimic the structure of the real pages (see
boffo_etl.sources.bom_pages); none of this is copied from real pages, and the
films and figures are invented.
"""

from __future__ import annotations

import gzip
import json
from datetime import date


def money(v: int | None) -> str:
    return "-" if v is None else f"${v:,}"


def num(v: int | None) -> str:
    return "-" if v is None else f"{v:,}"


NEW_HEADER = [
    ("Rank", "Rank"), ("Rank Last Week", "LW"), ("Release", "Release"), ("Weekend Gross", "Gross"),
    ("Gross Change/Week", "%± LW"), ("Number of Theaters", "Theaters"), ("Number of Theaters Change", "Change"),
    ("Per Theater Average Gross", "Average"), ("Total Gross", "Total Gross"),
    ("Number of Weeks In Release", "Weeks"), ("Distributor", "Distributor"),
    ("Is New This Week", "New This Week"), ("Estimated", "Estimated"),
]


def new_weekend_page(year: int, week: int, dates_text: str, rows: list[dict], *, area: str = "Domestic",
                     table: bool = True) -> str:
    """A new-style weekend chart. Row keys: rank, rl, title, gross, total, and optionally
    lw, label, theaters, weeks, dist, new, est."""
    head = "".join(
        f'<th class="a-text-right mojo-sortable-column"><a class="a-link-normal" title="{t}" href="?sort=x">'
        f'<span class="a-color-state">{v}</span></a></th>'
        for t, v in NEW_HEADER
    )
    body = []
    for r in rows:
        cls = []
        if r.get("new"):
            cls.append("mojo-annotation-isNewThisWeek")
        if r.get("est"):
            cls.append("mojo-annotation-isEstimated")
        label = (f'<div class="a-section a-spacing-none"><span class="a-size-small a-color-secondary">'
                 f'{r["label"]}</span></div>') if r.get("label") else ""
        link = (f'<a class="a-link-normal" href="/release/{r["rl"]}/?ref_=bo_we_table_1">{r["title"]}</a>'
                if r.get("rl") else r["title"])
        dist = (f'<a class="a-link-normal" target="_blank" href="https://pro.imdb.com/company/co0000001/'
                f'boxoffice/?view=releases">{r["dist"]}<svg class="mojo-new-window-svg" viewBox="0 0 32 32">'
                f'<path d="M24,15"></path></svg></a>') if r.get("dist") else "-"
        body.append(
            f'<tr class="{" ".join(cls)}">'
            f'<td class="a-text-right mojo-header-column mojo-field-type-rank">{r["rank"]}</td>'
            f'<td class="a-text-right mojo-field-type-positive_integer">{r.get("lw", "-")}</td>'
            f'<td class="a-text-left mojo-field-type-release mojo-cell-wide">{link}{label}</td>'
            f'<td class="a-text-right mojo-field-type-money mojo-estimatable">{money(r["gross"])}</td>'
            f'<td class="a-text-right mojo-field-type-percent_delta">-</td>'
            f'<td class="a-text-right mojo-field-type-positive_integer">{num(r.get("theaters"))}</td>'
            f'<td class="a-text-right mojo-field-type-integer">-</td>'
            f'<td class="a-text-right mojo-field-type-money">$1,000</td>'
            f'<td class="a-text-right mojo-field-type-money mojo-estimatable">{money(r["total"])}</td>'
            f'<td class="a-text-right mojo-field-type-positive_integer">{num(r.get("weeks"))}</td>'
            f'<td class="a-text-left mojo-field-type-release_studios">{dist}</td>'
            f'<td class="a-text-right mojo-field-type-boolean hidden">{"true" if r.get("new") else "false"}</td>'
            f'<td class="a-text-right mojo-field-type-boolean hidden">{"true" if r.get("est") else "false"}</td>'
            "</tr>"
        )
    chart = (f'<div class="a-section imdb-scroll-table-inner"><table class="a-bordered a-horizontal-stripes '
             f'mojo-body-table mojo-table-annotated"><tr>{head}</tr>{"".join(body)}</table></div>') if table else ""
    return (
        "<!doctype html><html><head><title>"
        f"{area} {year} Weekend {week} - Box Office Mojo</title>"
        "<script>var x = '<table><tr><td>not a table</td></tr></table>';</script></head><body>"
        '<div id="a-page"><main><div class="a-section a-spacing-none">'
        f'<h2>Weekend</h2><h1 class="mojo-gutter">{area} {year} Weekend {week}</h1>'
        f'<h4 class="mojo-gutter">{dates_text}</h4>'
        '<form><select name="weekend-view-navSelector"><option value="/weekend/x/">Weekend Chart</option>'
        "</select></form></div>"
        '<div class="a-section mojo-gutter"><h4>Key:<span class="mojo-annotation-key">New This Week</span>'
        '<span class="mojo-annotation-key">Estimated</span></h4></div>'
        f"{chart}</main></div></body></html>"
    )


def old_weekend_page(dates_text: str, rows: list[dict], *, estimates: bool = False) -> str:
    """An old-style chart: nested layout tables, <font> wrappers, unclosed cells, a colspan header.
    Row keys: rank, legacy, title, gross, total, and optionally lw, studio, theaters, weeks."""
    suffix = " (Estimates)" if estimates else ""
    head = ('<tr bgcolor="#dcdcdc"><td align="center"><font size="1"><b>TW</b></font>'
            '<td align="center"><font size="1"><b>LW</b></font>'
            '<td><font size="1"><b>Title (click to view)</b></font>'
            '<td><font size="1"><b>Studio</b></font>'
            '<td align="right"><font size="1"><b>Weekend Gross</b></font>'
            '<td align="right"><font size="1"><b>% Change</b></font>'
            '<td colspan="2" align="center"><font size="1"><b>Theater Count / Change</b></font>'
            '<td align="right"><font size="1"><b>Average</b></font>'
            '<td align="right"><font size="1"><b>Total Gross</b></font>'
            '<td align="right"><font size="1"><b>Budget*</b></font>'
            '<td align="center"><font size="1"><b>Week #</b></font></tr>')
    body = []
    for r in rows:
        body.append(
            f'<tr bgcolor="#ffffff"><td align="center"><font size="2">{r["rank"]}</font>'
            f'<td align="center"><font size="2">{r.get("lw", "N")}</font>'
            f'<td><font size="2"><a href="/movies/?id={r["legacy"]}.htm"><b>{r["title"]}</b></a></font>'
            f'<td><font size="2"><a href="/studio/chart/?studio=x.htm">{r.get("studio", "Uni.")}</a></font>'
            f'<td align="right"><font size="2"><b>{money(r["gross"])}</b></font>'
            '<td align="right"><font size="2">-</font>'
            f'<td align="right"><font size="2">{num(r.get("theaters"))}</font>'
            '<td align="right"><font size="2">-</font>'
            '<td align="right"><font size="2">$1,000</font>'
            f'<td align="right"><font size="2">{money(r["total"])}</font>'
            '<td align="right"><font size="2">-</font>'
            f'<td align="center"><font size="2">{num(r.get("weeks"))}</font></tr>'
        )
    return (
        f"<html><head><title>Weekend Box Office Results for {dates_text}{suffix} - Box Office Mojo</title>"
        "</head><body><table width=100%><tr><td>"
        '<table><tr><td width="25%"><font face="Verdana" size="1"><a href="/weekend/chart/?yr=2017&amp;wknd=04'
        '&amp;p=.htm"><b>&lt;&lt;Last Weekend</b></a></font><td align="center">View Index</td><td>&nbsp;</td></tr>'
        "</table>"
        f'<font face="Verdana" size="4"><b>{dates_text}</b></font>'
        f'<table border="0" cellpadding="5" cellspacing="1" width="98%">{head}{"".join(body)}</table>'
        "</td></tr></table></body></html>"
    )


def release_page(title: str, *, tt: str | None, release_date: date | None, mpaa: str = "PG-13",
                 genres: str = "Action\n    Adventure", distributor: str = "Example Pictures",
                 synopsis_tt: str | None = None, title_summary: bool = True) -> str:
    """Laid out like a real release page: heading (h1, then a synopsis that can link to
    another film), IMDbPro links for this film, the "Title Summary" link, then the summary."""
    def item(label, value):
        return f'<div class="a-section a-spacing-none"><span>{label}</span><span>{value}</span></div>'

    rd = (f'<a class="a-link-normal" href="/date/{release_date.isoformat()}/?ref_=bo_rl_rl">'
          f'{release_date.strftime("%b")} {release_date.day}, {release_date.year}</a>') if release_date else "-"
    synopsis = (f'<p class="a-size-medium">Years after <a class="a-link-normal" href="/title/{synopsis_tt}/?ref_=bo_rl_ti">'
                f'the last one</a>, they are back.</p>') if synopsis_tt else '<p class="a-size-medium">They are back.</p>'
    pro = (f'<div class="a-section mojo-heading-pro-cta"><div class="a-box"><div class="a-box-inner">'
           f'<a class="a-link-normal" href="https://pro.imdb.com/title/{tt}/cast">Cast information</a>'
           f'<a class="a-link-normal" href="https://pro.imdb.com/title/{tt}/boxoffice">Box office</a>'
           f'</div></div></div>') if tt else ""
    summary_link = (f'<div class="a-section mojo-title-release-refiner"><div id="title-summary-refiner">'
                    f'<a class="a-link-normal mojo-title-link refiner-display-highlight" href="/title/{tt}/?ref_=bo_rl_ti">'
                    f'Title Summary</a></div></div>') if tt and title_summary else ""
    return (
        f"<html><head><title>{title} - Box Office Mojo</title></head><body><main>"
        f'<div class="a-section mojo-heading-summary"><h1 class="a-size-extra-large">{title}</h1>{synopsis}</div>'
        f'{pro}{summary_link}'
        '<div class="a-section a-spacing-none mojo-summary-values mojo-hidden-from-mobile">'
        + item("Distributor", f'{distributor}<br><a class="a-size-small" href="https://pro.imdb.com/company/co1/">'
                              f'See full company information<svg viewBox="0 0 1 1"><path d="M0"/></svg></a>')
        + item("Opening", '<span class="money">$1,000,000</span><br>1,000 theaters')
        + item("Release Date", rd)
        + item("MPAA", mpaa)
        + item("Running Time", "2 hr 1 min")
        + item("Genres", genres)
        + "</div></main></body></html>"
    )


def cdx_json(captures: list[tuple[str, str]], *, status: str = "200", mime: str = "text/html") -> bytes:
    rows = [["timestamp", "original", "statuscode", "mimetype", "length"]]
    rows += [[ts, original, status, mime, "1234"] for ts, original in captures]
    return json.dumps(rows if captures else []).encode()


def cc_index_lines(records: list[dict]) -> bytes:
    return "\n".join(json.dumps(r) for r in records).encode() + b"\n"


def warc_record(html: str, *, status: int = 200, gzip_body: bool = False, chunked: bool = False) -> bytes:
    body = html.encode("utf-8")
    headers = [f"HTTP/1.1 {status} OK", "Content-Type: text/html; charset=UTF-8"]
    if gzip_body:
        body = gzip.compress(body)
        headers.append("Content-Encoding: gzip")
    if chunked:
        mid = len(body) // 2
        body = b"%x\r\n%s\r\n%x\r\n%s\r\n0\r\n\r\n" % (mid, body[:mid], len(body) - mid, body[mid:])
        headers.append("Transfer-Encoding: chunked")
    http = ("\r\n".join(headers) + "\r\n\r\n").encode() + body
    warc = (f"WARC/1.0\r\nWARC-Type: response\r\nWARC-Target-URI: https://www.boxofficemojo.com/x\r\n"
            f"Content-Length: {len(http)}\r\n\r\n").encode() + http + b"\r\n\r\n"
    return gzip.compress(warc)
