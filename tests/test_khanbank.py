from decimal import Decimal

from conftest import SAMPLE_ROWS, make_khan_xlsx
from finance.parsers import parse_statement


def test_parse_metadata_and_rows(khan_file):
    s = parse_statement(khan_file.read_bytes(), khan_file.name)
    assert s.bank_code == "KHAN"
    assert s.account_no == "5000111222"
    assert s.currency == "MNT"
    assert str(s.period_from) == "2026-08-14" and str(s.period_to) == "2026-10-14"
    assert len(s.transactions) == 4
    t0, t1 = s.transactions[0], s.transactions[1]
    assert t0.amount == Decimal("150000.00") and t0.counterparty_account == "5000999001"
    assert t1.amount == Decimal("-150000.00")
    assert s.transactions[3].counterparty_account is None
    assert s.warnings == []


def test_totals_mismatch_warns(tmp_path):
    p = make_khan_xlsx(tmp_path / "s.xlsx", SAMPLE_ROWS, ("1.00", "2.00"))
    s = parse_statement(p.read_bytes(), p.name)
    assert any("Totals" in w for w in s.warnings)


def test_missing_row_warns(tmp_path):
    rows = [SAMPLE_ROWS[0], SAMPLE_ROWS[3]]   # gap in balances
    p = make_khan_xlsx(tmp_path / "s.xlsx", rows)
    s = parse_statement(p.read_bytes(), p.name)
    assert any("missing rows" in w for w in s.warnings)


def test_dedupe_hash_stable(khan_file):
    a = parse_statement(khan_file.read_bytes(), khan_file.name)
    b = parse_statement(khan_file.read_bytes(), khan_file.name)
    ha = [t.dedupe_hash(a.account_no) for t in a.transactions]
    assert ha == [t.dedupe_hash(b.account_no) for t in b.transactions]
    assert len(set(ha)) == len(ha)


def test_unknown_file_rejected(tmp_path):
    import openpyxl
    import pytest
    wb = openpyxl.Workbook(); wb.active.append(["hello"]); p = tmp_path / "x.xlsx"; wb.save(p)
    with pytest.raises(ValueError):
        parse_statement(p.read_bytes(), p.name)
