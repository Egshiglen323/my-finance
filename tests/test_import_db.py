"""Needs a running PostgreSQL. Set TEST_DATABASE_URL to an EMPTY throwaway database, e.g.
   TEST_DATABASE_URL=postgresql://finance:finance@localhost:5432/finance_test
Skipped when the variable is not set. The test wipes that database."""
import os

import pytest

from conftest import SAMPLE_ROWS, make_khan_xlsx

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def conn():
    from finance.db import get_conn, migrate
    c = get_conn(URL)
    c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    migrate(c)
    yield c
    c.close()


def test_import_dedupe_and_classify(conn, tmp_path):
    from finance import repo
    from finance.classifier import classify
    from finance.importer import AlreadyImported, import_statement

    f1 = make_khan_xlsx(tmp_path / "a.xlsx", SAMPLE_ROWS)
    r = import_statement(conn, f1.read_bytes(), "a.xlsx")
    assert (r.rows_inserted, r.duplicates) == (4, 0)
    assert r.classified == 1                      # fee rule

    with pytest.raises(AlreadyImported):
        import_statement(conn, f1.read_bytes(), "a.xlsx")

    # overlapping statement: 2 old rows + 1 new row
    extra = ["2026-09-01 09:00:00", "5941", 0.0, 5000.0, 0.0, 5000.0, "q", "5000999001"]
    f2 = make_khan_xlsx(tmp_path / "b.xlsx", SAMPLE_ROWS[2:] + [extra])
    r2 = import_statement(conn, f2.read_bytes(), "b.xlsx")
    assert (r2.rows_inserted, r2.duplicates) == (1, 2)

    keys = {m["match_key"] for m in repo.unclassified_merchants(conn)}
    assert keys == {"ACC:5000999001", "ACC:5000999002", "DESC:EMART HUNNU"}

    repo.set_own_account(conn, "5000999002")
    classify(conn)
    keys = {m["match_key"] for m in repo.unclassified_merchants(conn)}
    assert "ACC:5000999002" not in keys
