"""All SQL used by the UI lives here, so app.py stays readable."""
from __future__ import annotations

import subprocess
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from .classifier import Rule, classify, forget_own_account_merchant, rule_matches

KIND_LABEL = {"income": "Income", "expense": "Expense", "transfer": "Transfer"}


# ---------------- categories ----------------
def categories(conn) -> list[dict]:
    return conn.execute(
        "SELECT id, name, kind, sort_order FROM categories "
        "ORDER BY CASE kind WHEN 'income' THEN 1 WHEN 'expense' THEN 2 ELSE 3 END, sort_order, name"
    ).fetchall()


def category_label(c: dict) -> str:
    return f"{KIND_LABEL[c['kind']]} › {c['name']}"


def category_maps(conn) -> tuple[dict[int, str], dict[str, int]]:
    cats = categories(conn)
    id_to_label = {c["id"]: category_label(c) for c in cats}
    return id_to_label, {v: k for k, v in id_to_label.items()}


def upsert_category(conn, cat_id: int | None, name: str, kind: str, sort_order: int = 100):
    if cat_id:
        conn.execute("UPDATE categories SET name=%s, kind=%s, sort_order=%s WHERE id=%s",
                     (name, kind, sort_order, cat_id))
    else:
        conn.execute("INSERT INTO categories (name, kind, sort_order) VALUES (%s, %s, %s) "
                     "ON CONFLICT (kind, name) DO NOTHING", (name, kind, sort_order))


def delete_category(conn, cat_id: int) -> int:
    """Delete a category. Its manual rows go back to automatic. Returns how many rules were removed with it."""
    with conn.transaction():
        conn.execute("UPDATE transactions SET class_source=NULL WHERE category_id=%s AND class_source='manual'",
                     (cat_id,))
        removed = conn.execute("DELETE FROM rules WHERE category_id=%s RETURNING id", (cat_id,)).fetchall()
        conn.execute("DELETE FROM categories WHERE id=%s", (cat_id,))
    return len(removed)


# ---------------- merchants ----------------
def unclassified_merchants(conn) -> list[dict]:
    """Merchants without a default category that still have unclassified transactions."""
    return conn.execute("""
        SELECT m.id, m.match_key, m.display_name,
               COUNT(t.id)                                        AS txn_count,
               COALESCE(SUM(t.amount) FILTER (WHERE t.amount > 0), 0)  AS money_in,
               COALESCE(-SUM(t.amount) FILTER (WHERE t.amount < 0), 0) AS money_out,
               MIN(t.txn_time) AS first_seen, MAX(t.txn_time) AS last_seen,
               (ARRAY_AGG(DISTINCT t.description))[1:3] AS samples,
               (ARRAY_AGG(DISTINCT t.counterparty_account)
                    FILTER (WHERE t.counterparty_account IS NOT NULL))[1:3] AS counterparties
        FROM merchants m
        JOIN transactions t ON t.merchant_id = m.id
        WHERE m.default_category_id IS NULL AND t.category_id IS NULL
        GROUP BY m.id
        ORDER BY COUNT(t.id) DESC, m.display_name
    """).fetchall()


def all_merchants(conn) -> list[dict]:
    return conn.execute("""
        SELECT m.id, m.match_key, m.display_name, m.default_category_id,
               COUNT(t.id) AS txn_count, COALESCE(SUM(t.amount), 0) AS net_amount,
               MAX(t.txn_time) AS last_seen
        FROM merchants m LEFT JOIN transactions t ON t.merchant_id = m.id
        GROUP BY m.id ORDER BY m.display_name
    """).fetchall()


def update_merchant(conn, merchant_id: int, display_name: str | None, category_id: int | None):
    conn.execute("UPDATE merchants SET display_name=COALESCE(%s, display_name), default_category_id=%s "
                 "WHERE id=%s", (display_name, category_id, merchant_id))


# ---------------- accounts ----------------
def accounts(conn) -> list[dict]:
    return conn.execute("""
        SELECT a.id, a.account_no, a.nickname, a.is_own, a.has_statements, a.currency, a.holder,
               b.name AS bank
        FROM accounts a LEFT JOIN banks b ON b.id = a.bank_id
        ORDER BY a.has_statements DESC, a.account_no
    """).fetchall()


def set_own_account(conn, account_no: str, is_own: bool = True, nickname: str | None = None):
    conn.execute(
        "INSERT INTO accounts (account_no, is_own, nickname) VALUES (%s, %s, %s) "
        "ON CONFLICT (account_no) DO UPDATE SET is_own = EXCLUDED.is_own, "
        "nickname = COALESCE(EXCLUDED.nickname, accounts.nickname)",
        (account_no, is_own, nickname))
    if is_own:
        forget_own_account_merchant(conn, account_no)


def update_account(conn, account_id: int, nickname: str | None, is_own: bool):
    old = conn.execute("SELECT account_no, is_own FROM accounts WHERE id=%s", (account_id,)).fetchone()
    conn.execute("UPDATE accounts SET nickname=%s, is_own=%s WHERE id=%s", (nickname, is_own, account_id))
    if old and is_own and not old["is_own"]:
        forget_own_account_merchant(conn, old["account_no"])


def account_label(a: dict) -> str:
    return f"{a['nickname']} ({a['account_no']})" if a.get("nickname") else a["account_no"]


# ---------------- transactions ----------------
def transactions(conn, date_from: date | None = None, date_to: date | None = None,
                 account_ids: list[int] | None = None, category_ids: list[int] | None = None,
                 unclassified_only: bool = False, search: str | None = None,
                 direction: str | None = None, limit: int = 5000) -> list[dict]:
    where, params = ["TRUE"], []
    if date_from:
        where.append("t.txn_time >= %s"); params.append(datetime.combine(date_from, datetime.min.time()))
    if date_to:
        where.append("t.txn_time < %s::date + 1"); params.append(date_to)
    if account_ids:
        where.append("t.account_id = ANY(%s)"); params.append(list(account_ids))
    if unclassified_only:
        where.append("t.category_id IS NULL")
    elif category_ids:
        where.append("t.category_id = ANY(%s)"); params.append(list(category_ids))
    if search:
        where.append("(t.description ILIKE %s OR t.counterparty_account ILIKE %s OR m.display_name ILIKE %s "
                     "OR t.note ILIKE %s)")
        params += [f"%{search}%"] * 4
    if direction == "in":
        where.append("t.amount > 0")
    elif direction == "out":
        where.append("t.amount < 0")
    params.append(limit)
    return conn.execute(f"""
        SELECT t.id, t.txn_time, a.account_no, t.amount, t.balance_after, t.description,
               t.counterparty_account, m.display_name AS merchant, t.category_id, t.class_source, t.note
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        LEFT JOIN merchants m ON m.id = t.merchant_id
        WHERE {' AND '.join(where)}
        ORDER BY t.txn_time DESC, t.id DESC
        LIMIT %s
    """, tuple(params)).fetchall()


def set_transaction_category(conn, txn_id: int, category_id: int | None, note: str | None = None):
    """Manual choice: sticks forever until you press 'Back to automatic'."""
    conn.execute("UPDATE transactions SET category_id=%s, class_source=%s, note=%s WHERE id=%s",
                 (category_id, "manual" if category_id else None, note, txn_id))


def set_note(conn, txn_id: int, note: str | None):
    conn.execute("UPDATE transactions SET note=%s WHERE id=%s", (note, txn_id))


def reset_to_auto(conn, txn_ids: list[int]) -> int:
    conn.execute("UPDATE transactions SET class_source=NULL, category_id=NULL WHERE id = ANY(%s)",
                 (list(txn_ids),))
    return classify(conn)


# ---------------- rules ----------------
def rules(conn) -> list[dict]:
    return conn.execute("SELECT id, priority, field, op, value, direction, category_id, active, note "
                        "FROM rules ORDER BY priority, id").fetchall()


def replace_rules(conn, rows: list[dict]):
    """Save the whole rules table as edited in the UI."""
    with conn.transaction():
        conn.execute("DELETE FROM rules")
        for r in rows:
            conn.execute(
                "INSERT INTO rules (priority, field, op, value, direction, category_id, active, note) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (int(r.get("priority") or 100), r["field"], r["op"], r["value"], r.get("direction") or None,
                 r["category_id"], bool(r.get("active", True)), r.get("note") or None))


def test_rule(conn, field: str, op: str, value: str, direction: str | None, limit: int = 200) -> list[dict]:
    rule = Rule(0, 0, field, op, value, direction or None, 0)
    rows = conn.execute("SELECT id, txn_time, amount, description, counterparty_account FROM transactions "
                        "ORDER BY txn_time DESC").fetchall()
    return [r for r in rows if rule_matches(rule, r["description"], r["counterparty_account"], r["amount"])][:limit]


# ---------------- reports ----------------
def monthly_summary(conn, date_from: date, date_to: date) -> list[dict]:
    return conn.execute("""
        SELECT to_char(date_trunc('month', t.txn_time), 'YYYY-MM') AS month,
               COALESCE(SUM(t.amount)  FILTER (WHERE c.kind = 'income'), 0)  AS income,
               COALESCE(-SUM(t.amount) FILTER (WHERE c.kind = 'expense'), 0) AS expense,
               COALESCE(SUM(t.amount)  FILTER (WHERE t.category_id IS NULL), 0) AS unclassified_net,
               COUNT(*) FILTER (WHERE t.category_id IS NULL) AS unclassified_count
        FROM transactions t LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.txn_time >= %s AND t.txn_time < %s::date + 1
        GROUP BY 1 ORDER BY 1
    """, (date_from, date_to)).fetchall()


def by_category(conn, date_from: date, date_to: date, kind: str) -> list[dict]:
    sign = -1 if kind == "expense" else 1
    return conn.execute("""
        SELECT c.name AS category, %s * SUM(t.amount) AS total, COUNT(*) AS txn_count
        FROM transactions t JOIN categories c ON c.id = t.category_id
        WHERE c.kind = %s AND t.txn_time >= %s AND t.txn_time < %s::date + 1
        GROUP BY c.name ORDER BY 2 DESC
    """, (sign, kind, date_from, date_to)).fetchall()


def top_merchants(conn, date_from: date, date_to: date, limit: int = 15) -> list[dict]:
    return conn.execute("""
        SELECT m.display_name AS merchant, c.name AS category, -SUM(t.amount) AS spent, COUNT(*) AS txn_count
        FROM transactions t
        JOIN merchants m ON m.id = t.merchant_id
        LEFT JOIN categories c ON c.id = t.category_id
        WHERE t.amount < 0 AND COALESCE(c.kind, 'expense') = 'expense'
          AND t.txn_time >= %s AND t.txn_time < %s::date + 1
        GROUP BY m.display_name, c.name ORDER BY 3 DESC LIMIT %s
    """, (date_from, date_to, limit)).fetchall()


def daily_balances(conn, date_from: date, date_to: date) -> list[dict]:
    """Last known balance of each statement account per day."""
    return conn.execute("""
        SELECT DISTINCT ON (a.account_no, t.txn_time::date)
               t.txn_time::date AS day, COALESCE(a.nickname, a.account_no) AS account, t.balance_after AS balance
        FROM transactions t JOIN accounts a ON a.id = t.account_id
        WHERE t.balance_after IS NOT NULL AND t.txn_time >= %s AND t.txn_time < %s::date + 1
        ORDER BY a.account_no, t.txn_time::date, t.txn_time DESC, t.id DESC
    """, (date_from, date_to)).fetchall()


def date_bounds(conn) -> tuple[date | None, date | None]:
    r = conn.execute("SELECT MIN(txn_time)::date AS lo, MAX(txn_time)::date AS hi FROM transactions").fetchone()
    return r["lo"], r["hi"]


def imports(conn) -> list[dict]:
    return conn.execute("""
        SELECT i.id, i.imported_at, i.file_name, a.account_no, i.period_from, i.period_to,
               i.rows_read, i.rows_inserted
        FROM imports i JOIN accounts a ON a.id = i.account_id ORDER BY i.imported_at DESC
    """).fetchall()


# ---------------- backup ----------------
def backup(database_url: str, out_dir: Path) -> Path:
    """Run pg_dump into out_dir/finance_YYYYmmdd_HHMMSS.sql (pg_dump must be on PATH)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"finance_{datetime.now():%Y%m%d_%H%M%S}.sql"
    u = urlparse(database_url)
    env = None
    if u.password:
        import os
        env = {**os.environ, "PGPASSWORD": u.password}
    cmd = ["pg_dump", "--no-owner", "-h", u.hostname or "localhost", "-p", str(u.port or 5432),
           "-U", u.username or "postgres", "-f", str(out), (u.path or "/finance").lstrip("/")]
    subprocess.run(cmd, check=True, env=env, capture_output=True)
    return out
