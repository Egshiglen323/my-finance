"""Automatic classification.

Order for each transaction (first hit wins). Manual choices are never touched.
  1. merchant default  - you picked a category for this merchant on the Classify page
  2. rules             - Rules page, lowest priority number first
  3. own account       - counterparty is one of your own accounts -> 'Own-account transfer'
  otherwise unclassified -> shows up on the Classify page.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Rule:
    id: int
    priority: int
    field: str
    op: str
    value: str
    direction: str | None
    category_id: int


def rule_matches(rule: Rule, description: str | None, counterparty: str | None, amount: Decimal) -> bool:
    if rule.direction == "credit" and amount <= 0:
        return False
    if rule.direction == "debit" and amount >= 0:
        return False

    if rule.field == "amount":
        if rule.op != "between":
            try:
                return abs(amount) == Decimal(rule.value.strip())
            except Exception:
                return False
        try:
            lo, hi = (Decimal(x.strip()) if x.strip() else None for x in rule.value.split(",", 1))
        except Exception:
            return False
        a = abs(amount)
        return (lo is None or a >= lo) and (hi is None or a <= hi)

    text = (description if rule.field == "description" else counterparty) or ""
    value = rule.value or ""
    if rule.op == "contains":
        return value.upper() in text.upper()
    if rule.op == "equals":
        return text.strip().upper() == value.strip().upper()
    if rule.op == "regex":
        try:
            return re.search(value, text, re.IGNORECASE) is not None
        except re.error:
            return False
    return False


def decide(txn: dict, rules: list[Rule], merchant_defaults: dict[int, int | None],
           own_accounts: set[str], own_category_id: int | None):
    """Return (category_id, class_source) or (None, None)."""
    m = txn.get("merchant_id")
    if m is not None and merchant_defaults.get(m):
        return merchant_defaults[m], "merchant"
    for r in rules:
        if rule_matches(r, txn.get("description"), txn.get("counterparty_account"), Decimal(txn["amount"])):
            return r.category_id, "rule"
    if own_category_id and txn.get("counterparty_account") in own_accounts:
        return own_category_id, "own_account"
    return None, None


def forget_own_account_merchant(conn, account_no: str):
    """An own account must end up as 'Own-account transfer', but a merchant default is checked first.
    So drop the default of the 'ACC:<account_no>' merchant when the account becomes own."""
    conn.execute("UPDATE merchants SET default_category_id=NULL WHERE match_key=%s", (f"ACC:{account_no}",))


def load_rules(conn) -> list[Rule]:
    rows = conn.execute(
        "SELECT id, priority, field, op, value, direction, category_id FROM rules "
        "WHERE active ORDER BY priority, id").fetchall()
    return [Rule(**r) for r in rows]


def classify(conn, import_id: int | None = None) -> int:
    """(Re)classify every non-manual transaction (or only one import's). Returns rows changed."""
    rules = load_rules(conn)
    merchant_defaults = {r["id"]: r["default_category_id"]
                         for r in conn.execute("SELECT id, default_category_id FROM merchants").fetchall()}
    own_accounts = {r["account_no"] for r in conn.execute("SELECT account_no FROM accounts WHERE is_own").fetchall()}
    row = conn.execute("SELECT id FROM categories WHERE kind='transfer' AND name='Own-account transfer'").fetchone()
    own_cat = row["id"] if row else None

    sql = ("SELECT id, description, counterparty_account, amount, merchant_id, category_id, class_source "
           "FROM transactions WHERE class_source IS DISTINCT FROM 'manual'")
    params: tuple = ()
    if import_id is not None:
        sql += " AND import_id = %s"
        params = (import_id,)

    updates = []
    for t in conn.execute(sql, params).fetchall():
        cat, src = decide(t, rules, merchant_defaults, own_accounts, own_cat)
        if cat != t["category_id"] or src != t["class_source"]:
            updates.append((cat, src, t["id"]))
    if updates:
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany("UPDATE transactions SET category_id=%s, class_source=%s WHERE id=%s", updates)
    return len(updates)
