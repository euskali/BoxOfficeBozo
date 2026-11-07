from __future__ import annotations

from datetime import date

import pytest

from bom_html import new_weekend_page, old_weekend_page, release_page
from boffo_etl import htmltables
from boffo_etl.sources.bom_pages import (
    NotAChart,
    parse_date_range,
    parse_int,
    parse_new_weekend,
    parse_old_weekend,
    parse_release_page,
)

ROWS = [
    {"rank": 1, "lw": 1, "rl": "rl100", "title": "Space Saga: Part Nine", "gross": 34_000_000, "theaters": 4_400,
     "total": 450_000_000, "weeks": 3, "dist": "Example Pictures"},
    {"rank": 2, "rl": "rl200", "title": "The Grudge Match", "gross": 11_000_000, "theaters": 2_600,
     "total": 11_000_000, "weeks": 1, "dist": "Other Films", "new": True},
    {"rank": 3, "lw": 9, "rl": "rl300", "title": "The White Hat", "label": "2019 re-release", "gross": 3_000,
     "theaters": None, "total": 9_500, "weeks": 2, "est": True},
]


@pytest.mark.parametrize("text, expected", [
    ("January 3-5, 2020", (date(2020, 1, 3), date(2020, 1, 5))),
    ("January 31-February 2, 2020", (date(2020, 1, 31), date(2020, 2, 2))),
    ("December 31, 2021-January 2, 2022", (date(2021, 12, 31), date(2022, 1, 2))),
    ("December 30-January 1, 2017", (date(2016, 12, 30), date(2017, 1, 1))),
    ("Weekend Box Office Results for Sept 1-3, 2017 - Box Office Mojo", (date(2017, 9, 1), date(2017, 9, 3))),
    ("May 24–26, 2019", (date(2019, 5, 24), date(2019, 5, 26))),
])
def test_parse_date_range(text, expected):
    assert parse_date_range(text) == expected


def test_parse_date_range_rejects_nonsense():
    assert parse_date_range("Key: New This Week") is None
    assert parse_date_range("Smarch 3-5, 2020") is None


@pytest.mark.parametrize("text, expected", [
    ("$34,524,815", 34_524_815), ("4,406", 4406), ("-", None), ("", None), ("n/a", None), ("+174", 174),
    ("$1.2 million", None), (None, None),
])
def test_parse_int(text, expected):
    assert parse_int(text) == expected


def test_new_weekend_chart():
    page = parse_new_weekend(new_weekend_page(2020, 1, "January 3-5, 2020", ROWS))
    assert (page.style, page.year, page.week) == ("new", 2020, 1)
    assert (page.start, page.end) == (date(2020, 1, 3), date(2020, 1, 5))
    assert [r.key for r in page.rows] == ["rl100", "rl200", "rl300"]
    a, b, c = page.rows
    assert (a.rank, a.title, a.label, a.weekend_gross, a.theaters, a.total_gross, a.weeks, a.distributor) == (
        1, "Space Saga: Part Nine", None, 34_000_000, 4_400, 450_000_000, 3, "Example Pictures")
    assert (a.is_new, a.is_estimate) == (False, False)
    assert (b.is_new, b.is_estimate) == (True, False)
    assert (c.title, c.label, c.theaters, c.distributor, c.is_estimate) == (
        "The White Hat", "2019 re-release", None, None, True)


def test_new_weekend_chart_ignores_tables_inside_scripts():
    page = parse_new_weekend(new_weekend_page(2020, 1, "January 3-5, 2020", ROWS[:1]))
    assert len(page.rows) == 1


def test_new_weekend_chart_without_rows_is_empty_not_an_error():
    page = parse_new_weekend(new_weekend_page(2020, 15, "April 10-12, 2020", []))
    assert page.rows == [] and page.end == date(2020, 4, 12)


def test_new_weekend_chart_counts_rows_without_a_release_link():
    page = parse_new_weekend(new_weekend_page(2020, 1, "January 3-5, 2020",
                                              ROWS[:1] + [{"rank": 2, "title": "Unlinked", "gross": 5, "total": 5}]))
    assert len(page.rows) == 1 and page.unkeyed_rows == 1


@pytest.mark.parametrize("html", [
    "<html><head><title>Sorry! Something went wrong!</title></head><body><p>Robot check</p></body></html>",
    new_weekend_page(2020, 1, "January 3-5, 2020", ROWS, table=False),
    new_weekend_page(2020, 1, "January 3-5, 2020", ROWS, area="United Kingdom"),
])
def test_not_a_new_weekend_chart(html):
    with pytest.raises(NotAChart):
        parse_new_weekend(html)


OLD_ROWS = [
    {"rank": 1, "lw": "1", "legacy": "split2017", "title": "Splitting", "studio": "Uni.", "gross": 14_424_195,
     "theaters": 3_373, "total": 98_540_660, "weeks": 3},
    {"rank": 2, "legacy": "rings", "title": "Rings & Things", "studio": "Par.", "gross": 13_002_632,
     "theaters": 2_931, "total": 13_002_632, "weeks": 1},
    {"rank": 3, "lw": "-", "legacy": "Moonlight2016", "title": "Moonglow (2016)", "studio": "A24", "gross": 99,
     "theaters": None, "total": 31_577, "weeks": 29},
]


def test_old_weekend_chart():
    page = parse_old_weekend(old_weekend_page("February 3-5, 2017", OLD_ROWS))
    assert page.style == "old" and (page.start, page.end) == (date(2017, 2, 3), date(2017, 2, 5))
    assert [r.key for r in page.rows] == ["split2017", "rings", "moonlight2016"]
    a, b, c = page.rows
    assert (a.rank, a.title, a.distributor, a.weekend_gross, a.theaters, a.total_gross, a.weeks, a.is_new) == (
        1, "Splitting", "Uni.", 14_424_195, 3_373, 98_540_660, 3, False)
    assert (b.title, b.is_new) == ("Rings & Things", True)
    assert (c.theaters, c.weeks, c.is_estimate) == (None, 29, None)


def test_old_weekend_estimates_page_marks_rows():
    page = parse_old_weekend(old_weekend_page("February 3-5, 2017", OLD_ROWS, estimates=True))
    assert all(r.is_estimate for r in page.rows)


def test_not_an_old_weekend_chart():
    with pytest.raises(NotAChart):
        parse_old_weekend("<html><head><title>Box Office Mojo</title></head><body></body></html>")
    with pytest.raises(NotAChart):
        parse_old_weekend("<html><head><title>Weekend Box Office Results for February 3-5, 2017</title>"
                          "</head><body><table><tr><td>no chart</td></tr></table></body></html>")


def test_release_page():
    info = parse_release_page(release_page("Space Saga: Part Nine", tt="tt1234567", release_date=date(2019, 12, 20)))
    assert info.tt_id == "tt1234567"
    assert info.title == "Space Saga: Part Nine"
    assert info.release_date == date(2019, 12, 20)
    assert (info.mpaa, info.genres, info.running_time) == ("PG-13", "Action Adventure", "2 hr 1 min")
    assert info.distributor == "Example Pictures"


def test_release_page_ignores_a_synopsis_link_to_another_film():
    # Real pages link the previous film in the synopsis, ahead of the release's own links.
    page = release_page("Space Saga: Part Ten", tt="tt7654321", release_date=date(2021, 5, 7), synopsis_tt="tt1234567")
    assert parse_release_page(page).tt_id == "tt7654321"
    # Without the "Title Summary" link, the IMDbPro links outside the synopsis still name it.
    page = release_page("Space Saga: Part Ten", tt="tt7654321", release_date=None, synopsis_tt="tt1234567",
                        title_summary=False)
    assert parse_release_page(page).tt_id == "tt7654321"


def test_release_page_with_only_a_synopsis_link_has_no_title():
    info = parse_release_page(release_page("Odd Sequel", tt=None, release_date=None, synopsis_tt="tt1234567"))
    assert info.tt_id is None


def test_release_page_without_title_link():
    info = parse_release_page(release_page("Odd One", tt=None, release_date=None))
    assert info.tt_id is None and info.release_date is None and info.mpaa == "PG-13"


def test_release_page_rejects_other_pages():
    with pytest.raises(NotAChart):
        parse_release_page("<html><body><p>Page not found</p></body></html>")


def test_htmltables_unclosed_cells_and_nested_tables():
    page = htmltables.parse(
        "<table><tr><td>outer<table><tr><td>a<td>b<a href='/x'>link</a><tr><td>c</table>tail</td></tr></table>")
    outer, inner = page.tables
    assert inner.depth == 1 and [[c.text for c in r.cells] for r in inner.rows] == [["a", "b link"], ["c"]]
    assert inner.rows[0].cells[1].links == [("/x", "link")]
    assert outer.rows[0].cells[0].text == "outer tail"


def test_htmltables_secondary_text_and_titles():
    page = htmltables.parse('<table><tr><th><a title="Weekend Gross">Gross</a></th></tr><tr><td><a href="/r">Film'
                            '</a><div><span class="a-color-secondary">IMAX</span></div><span>more</span></td></tr>'
                            "</table>")
    th = page.tables[0].rows[0].cells[0]
    td = page.tables[0].rows[1].cells[0]
    assert th.titles == ["Weekend Gross"] and th.text == "Gross"
    assert td.secondary == "IMAX" and td.text == "Film IMAX more"
