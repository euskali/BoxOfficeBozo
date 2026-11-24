from __future__ import annotations

from pathlib import Path

import pytest

from boffo_etl.manual import SCHEMAS, load_manual, validate_manual_dir

from conftest import REAL_REPO_ROOT


def errors(issues):
    return [i for i in issues if i.severity == "error"]


def test_committed_manual_dir_is_valid():
    issues = validate_manual_dir(REAL_REPO_ROOT / "data" / "manual")
    assert errors(issues) == []


def test_committed_manual_csvs_have_exact_headers():
    for name, schema in SCHEMAS.items():
        lines = (REAL_REPO_ROOT / "data" / "manual" / name).read_text(encoding="utf-8").splitlines()
        assert lines[0] == ",".join(schema.columns), name


def write(repo: Path, name: str, *rows: str, header: str | None = None) -> None:
    head = header if header is not None else ",".join(SCHEMAS[name].columns)
    (repo / "data" / "manual" / name).write_text("\n".join([head, *rows]) + "\n", encoding="utf-8")


def test_clean_repo_ok(repo):
    assert validate_manual_dir(repo / "data" / "manual") == []


GOOD_TP = "1990,4.23,Some Published Table,https://example.org/t,"


def test_valid_ticket_row(repo):
    write(repo, "ticket_prices.csv", GOOD_TP)
    assert validate_manual_dir(repo / "data" / "manual") == []
    assert load_manual("ticket_prices.csv", repo / "data" / "manual")[0]["year"] == 1990


@pytest.mark.parametrize("src", ["", "   ", "TODO", "tbd", "N/A", "?", "-", "Made Up", "see TODO later", "fixme: x"])
def test_bad_source(repo, src):
    write(repo, "ticket_prices.csv", f'1990,4.23,"{src}",,')
    assert errors(validate_manual_dir(repo / "data" / "manual"))


def test_bad_header(repo):
    write(repo, "ticket_prices.csv", header="year,price,source,source_url,notes")
    es = errors(validate_manual_dir(repo / "data" / "manual"))
    assert es and "header" in es[0].message


def test_duplicate_key(repo):
    write(repo, "ticket_prices.csv", GOOD_TP, GOOD_TP)
    es = errors(validate_manual_dir(repo / "data" / "manual"))
    assert len(es) == 1 and "duplicate" in es[0].message and es[0].line == 3


@pytest.mark.parametrize("url", ["ftp://x.org", "www.example.org", "example.org/a"])
def test_non_http_source_url(repo, url):
    write(repo, "ticket_prices.csv", f"1990,4.23,Cite,{url},")
    assert errors(validate_manual_dir(repo / "data" / "manual"))


@pytest.mark.parametrize("row", ["1899,4,Cite,,", "2101,4,Cite,,", "1990,0,Cite,,", "1990,-1,Cite,,", "abc,1,Cite,,"])
def test_ticket_ranges(repo, row):
    write(repo, "ticket_prices.csv", row)
    assert errors(validate_manual_dir(repo / "data" / "manual"))


def test_baseline_rules(repo):
    good = "Some Film,1977,Q123,tt0000123,1000000,1981-12-31,false,Cite,https://example.org,"
    write(repo, "pre1982_baseline.csv", good)
    assert validate_manual_dir(repo / "data" / "manual") == []
    for bad in [
        good.replace(",1977,", ",1982,"),
        good.replace("1981-12-31", "1982-01-01"),
        good.replace(",false,", ",maybe,"),
        good.replace("Q123", "123"),
        good.replace("tt0000123", "tt12"),
        good.replace(",1000000,", ",0,"),
    ]:
        write(repo, "pre1982_baseline.csv", bad)
        assert errors(validate_manual_dir(repo / "data" / "manual")), bad


def test_baseline_pk_falls_back_to_title_year(repo):
    row = "Some Film,1977,,,1000000,1981-12-31,true,Cite,,"
    write(repo, "pre1982_baseline.csv", row, row)
    assert any("duplicate" in e.message for e in errors(validate_manual_dir(repo / "data" / "manual")))


def test_admissions_estimate_rules(repo):
    good = "Some Film,tt0000123,178119600,2018-12-22,Cite,https://example.org,"
    write(repo, "admissions_estimates.csv", good)
    assert validate_manual_dir(repo / "data" / "manual") == []
    row = load_manual("admissions_estimates.csv", repo / "data" / "manual")[0]
    assert (row["admissions"], str(row["as_of"])) == (178119600, "2018-12-22")
    for bad in [
        good.replace(",178119600,", ",0,"),
        good.replace(",178119600,", ",1.5e8,"),
        good.replace("2018-12-22", "22 Dec 2018"),
        good.replace("tt0000123", "bb_some_film"),
        good.replace(",Cite,", ",TODO,"),
    ]:
        write(repo, "admissions_estimates.csv", bad)
        assert errors(validate_manual_dir(repo / "data" / "manual")), bad
    write(repo, "admissions_estimates.csv", good, good)
    assert any("duplicate" in e.message for e in errors(validate_manual_dir(repo / "data" / "manual")))


def test_id_override_and_groups(repo):
    write(repo, "id_overrides.csv", "ongoldenpond,tt0082846,,,Cite,,", "x,bb_foo_1,,,Cite,,")
    write(repo, "title_groups.csv", "k1,tt1234567,Label,Cite,,")
    assert validate_manual_dir(repo / "data" / "manual") == []
    write(repo, "id_overrides.csv", "k,BB_foo,,,Cite,,")
    assert errors(validate_manual_dir(repo / "data" / "manual"))


def test_unknown_csv_is_warning(repo):
    (repo / "data" / "manual" / "extra.csv").write_text("a,b\n", encoding="utf-8")
    issues = validate_manual_dir(repo / "data" / "manual")
    assert [i.severity for i in issues] == ["warning"]
