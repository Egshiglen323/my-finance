"""Needs TEST_DATABASE_URL (an empty throwaway database; it is wiped). Skipped otherwise."""
import os
from datetime import date

import pytest

from conftest import SAMPLE_ROWS, make_khan_xlsx

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def conn(tmp_path):
    from finance.db import get_conn, migrate
    from finance.importer import import_statement
    c = get_conn(URL)
    c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    migrate(c)
    f = make_khan_xlsx(tmp_path / "a.xlsx", SAMPLE_ROWS)
    import_statement(c, f.read_bytes(), "a.xlsx")
    yield c
    c.close()


def test_categories_and_labels(conn):
    from finance import repo
    id2l, l2id = repo.category_maps(conn)
    assert "Expense › Groceries" in l2id
    assert "Income › Gift / Donation received" in l2id
    assert "Transfer › Own-account transfer" in l2id
    assert id2l[l2id["Expense › Bank fees"]] == "Expense › Bank fees"


def test_manual_category_sticks_and_resets(conn):
    from finance import repo
    from finance.classifier import classify
    _, l2id = repo.category_maps(conn)
    fee = repo.transactions(conn, search="ХУРААМЖ")[0]
    assert fee["class_source"] == "rule"
    repo.set_transaction_category(conn, fee["id"], l2id["Expense › Other expense"], "my note")
    classify(conn)
    row = repo.transactions(conn, search="ХУРААМЖ")[0]
    assert (row["class_source"], row["category_id"], row["note"]) == ("manual", l2id["Expense › Other expense"], "my note")
    repo.reset_to_auto(conn, [fee["id"]])
    row = repo.transactions(conn, search="ХУРААМЖ")[0]
    assert (row["class_source"], row["category_id"]) == ("rule", l2id["Expense › Bank fees"])


def test_transaction_filters(conn):
    from finance import repo
    assert len(repo.transactions(conn)) == 4
    assert len(repo.transactions(conn, direction="in")) == 1
    assert len(repo.transactions(conn, direction="out")) == 3
    assert len(repo.transactions(conn, unclassified_only=True)) == 3
    assert len(repo.transactions(conn, date_from=date(2026, 8, 25), date_to=date(2026, 8, 25))) == 1
    assert len(repo.transactions(conn, search="emart")) == 1


def test_merchant_default_and_reports(conn):
    from finance import repo
    from finance.classifier import classify
    _, l2id = repo.category_maps(conn)
    m = next(m for m in repo.unclassified_merchants(conn) if m["match_key"] == "DESC:EMART HUNNU")
    assert m["txn_count"] == 1 and float(m["money_out"]) == 7.0
    repo.update_merchant(conn, m["id"], "E-Mart", l2id["Expense › Groceries"])
    classify(conn)
    rows = {r["category"]: float(r["total"]) for r in repo.by_category(conn, date(2026, 8, 1), date(2026, 8, 31), "expense")}
    assert rows == {"Groceries": 7.0, "Bank fees": 93.76}
    month = repo.monthly_summary(conn, date(2026, 8, 1), date(2026, 8, 31))[0]
    assert month["month"] == "2026-08" and float(month["expense"]) == 100.76
    assert repo.date_bounds(conn) == (date(2026, 8, 21), date(2026, 8, 31))
