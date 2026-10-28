"""Upload -> parse -> store (skipping duplicates) -> auto-classify."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .classifier import classify, forget_own_account_merchant
from .merchants import merchant_key
from .parsers import parse_statement
from .parsers.base import Statement


class AlreadyImported(Exception):
    pass


@dataclass
class ImportResult:
    import_id: int
    statement: Statement
    rows_read: int
    rows_inserted: int
    duplicates: int
    classified: int
    new_merchants: int


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def preview(data: bytes, file_name: str) -> Statement:
    """Parse only (nothing is saved) - used to show a summary before importing."""
    return parse_statement(data, file_name)


def import_statement(conn, data: bytes, file_name: str) -> ImportResult:
    sha = file_hash(data)
    if conn.execute("SELECT 1 FROM imports WHERE file_sha256=%s", (sha,)).fetchone():
        raise AlreadyImported(f"'{file_name}' was already imported.")

    stmt = parse_statement(data, file_name)

    with conn.transaction():
        bank = conn.execute(
            "INSERT INTO banks (code, name) VALUES (%s, %s) "
            "ON CONFLICT (code) DO UPDATE SET name = banks.name RETURNING id",
            (stmt.bank_code, stmt.bank_name)).fetchone()
        account = conn.execute(
            "INSERT INTO accounts (bank_id, account_no, iban, currency, holder, is_own, has_statements) "
            "VALUES (%s, %s, %s, %s, %s, TRUE, TRUE) "
            "ON CONFLICT (account_no) DO UPDATE SET bank_id = EXCLUDED.bank_id, "
            "  iban = COALESCE(EXCLUDED.iban, accounts.iban), holder = COALESCE(EXCLUDED.holder, accounts.holder), "
            "  currency = EXCLUDED.currency, is_own = TRUE, has_statements = TRUE "
            "RETURNING id",
            (bank["id"], stmt.account_no, stmt.iban, stmt.currency, stmt.holder)).fetchone()
        forget_own_account_merchant(conn, stmt.account_no)
        imp = conn.execute(
            "INSERT INTO imports (account_id, file_name, file_sha256, period_from, period_to, rows_read) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (account["id"], file_name, sha, stmt.period_from, stmt.period_to, len(stmt.transactions))).fetchone()

        merchant_ids: dict[str, int] = {}
        new_merchants = 0
        inserted = 0
        for t in stmt.transactions:
            key, display = merchant_key(t.description, t.counterparty_account)
            if key not in merchant_ids:
                row = conn.execute(
                    "INSERT INTO merchants (match_key, display_name) VALUES (%s, %s) "
                    "ON CONFLICT (match_key) DO NOTHING RETURNING id", (key, display)).fetchone()
                if row:
                    new_merchants += 1
                else:
                    row = conn.execute("SELECT id FROM merchants WHERE match_key=%s", (key,)).fetchone()
                merchant_ids[key] = row["id"]
            row = conn.execute(
                "INSERT INTO transactions (account_id, import_id, txn_time, branch, amount, balance_before, "
                " balance_after, description, counterparty_account, merchant_id, dedupe_hash) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (dedupe_hash) DO NOTHING RETURNING id",
                (account["id"], imp["id"], t.txn_time, t.branch, t.amount, t.balance_before, t.balance_after,
                 t.description, t.counterparty_account, merchant_ids[key], t.dedupe_hash(stmt.account_no))
            ).fetchone()
            if row:
                inserted += 1
        conn.execute("UPDATE imports SET rows_inserted=%s WHERE id=%s", (inserted, imp["id"]))

    # every row, not just this import: this account is now known as own, which changes older rows too
    classified = classify(conn)
    return ImportResult(imp["id"], stmt, len(stmt.transactions), inserted,
                        len(stmt.transactions) - inserted, classified, new_merchants)
