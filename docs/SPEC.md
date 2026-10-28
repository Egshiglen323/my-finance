# SPEC — Personal finance tool (read this before every task)

## Product
Single-user local app on a personal PC. The user uploads bank statements (Excel) from time to time. The app stores the transactions in PostgreSQL, auto-classifies them, lists new merchants for the user to classify, and allows manual overrides. Bank #1 is Khan Bank (Mongolia); more banks come later through a parser plugin.

## Stack (do not add anything else)
Python 3.10+, PostgreSQL, `psycopg` v3 (NOT psycopg2, NO SQLAlchemy, NO ORM), `pandas`, `openpyxl`, `streamlit`, `python-dotenv`, `pytest`.

## Folder layout (final)
```
app.py                      Streamlit UI
finance/__init__.py         (empty)
finance/db.py               get_conn(), migrate()
finance/parsers/__init__.py exports parse_statement, PARSERS
finance/parsers/base.py     Transaction, Statement, BankParser, helpers
finance/parsers/khanbank.py KhanBankParser
finance/parsers/registry.py PARSERS list, load_grid(), parse_statement()
finance/merchants.py        normalize(), merchant_key()
finance/classifier.py       Rule, rule_matches(), decide(), load_rules(), classify()
finance/importer.py         AlreadyImported, ImportResult, file_hash(), preview(), import_statement()
finance/repo.py             every SQL query the UI needs
migrations/001_schema.sql   PROVIDED — never edit
migrations/002_seed.sql     PROVIDED — never edit
tests/                      PROVIDED — never edit
```

## Code conventions
- `from __future__ import annotations` at the top of every module.
- Money is always `decimal.Decimal`, quantized to 0.01. Never use float for stored values.
- DB connection: `psycopg.connect(url, row_factory=dict_row, autocommit=True)`. Rows are dicts. Use `with conn.transaction():` for multi-statement atomic work. Always use `%s` parameters, never f-strings with values.
- `amount` sign: **+ money in (credit), − money out (debit)**.
- Keep functions small; no classes except where listed; no logging framework; no comments that restate code.

## Database (from migrations/001_schema.sql — summary)
- `banks(id, code UNIQUE, name)`
- `accounts(id, bank_id, account_no UNIQUE, iban, currency, holder, nickname, is_own BOOL, has_statements BOOL)`
- `imports(id, account_id, file_name, file_sha256 UNIQUE, period_from, period_to, rows_read, rows_inserted, imported_at)`
- `categories(id, name, kind IN ('income','expense','transfer'), sort_order, UNIQUE(kind,name))`
- `merchants(id, match_key UNIQUE, display_name, default_category_id)`
- `rules(id, priority, field IN ('description','counterparty','amount'), op IN ('contains','equals','regex','between'), value, direction IN ('credit','debit') or NULL, category_id, active, note)`
- `transactions(id, account_id, import_id, txn_time, branch, amount, balance_before, balance_after, description, counterparty_account, merchant_id, category_id, class_source IN ('merchant','rule','own_account','manual') or NULL, note, dedupe_hash UNIQUE)`
- `schema_migrations(name PK, applied_at)` is created by `migrate()`.
- Seeded categories include: income: "Self-earned (salary, freelance)", "Gift / Donation received", "Refund", "Interest", "Other income"; expense: "Personal care", "Groceries", "Healthcare", "Savings", "Food & cafés", "Transport (taxi, fuel, bus)", "Utilities (power, heating, internet)", "Mobile & subscriptions", "Housing / Rent", "Education", "Clothing & shopping", "Entertainment", "Gifts / Donations given", "Loan repayment", "Bank fees", "Other expense"; transfer: "Own-account transfer", "Cash withdrawal".
- Seeded rules: description contains `ХУРААМЖ` (debit) → Bank fees (priority 10); description regex `\bATM\b` (debit) → Cash withdrawal (priority 50).

## Khan Bank statement format (real export, .xlsx, one sheet)
- Row 1 (metadata, label cell followed by value cell): `Хэвлэсэн огноо:` `10/14/2026` · `Депозит дансны дэлгэрэнгүй хуулга` · `Хэрэглэгч:` `<NAME>` · `Интервал:` `2026/08/14` `-` `2026/10/14` · `Валют:` `MNT` · one cell `IBAN: MN660005005954230716`
- IBAN = `MN` + 2 check digits + 4-digit bank code (`0005` = Khan Bank) + 12-digit account with leading zeros → account_no `5954230716`.
- Row 2 header (map by NAME, not position):
  | Mongolian | field |
  |---|---|
  | Гүйлгээний огноо | txn_time (string `2026-08-21 12:53:59`) |
  | Салбар | branch (string) |
  | Эхний үлдэгдэл | balance_before |
  | Кредит гүйлгээ | credit (≥ 0) |
  | Дебит гүйлгээ | debit (stored NEGATIVE, e.g. -150000.0) |
  | Эцсийн үлдэгдэл | balance_after |
  | Гүйлгээний утга | description (often junk like `q`, `1`) |
  | Харьцсан данс | counterparty account (string or empty) |
- Then transaction rows, then blank rows, then a totals row whose first cell is `Нийт дүн:` with credit total in the credit column and debit total (positive string, e.g. `"1536091.76"`) in the debit column.
- Sample rows:
  `2026-08-21 12:53:59 | 5941 | 100.76 | 150000.0 | 0.0 | 150100.76 | q | 5954114905`
  `2026-08-21 12:54:25 | 5003 | 150100.76 | 0.0 | -150000.0 | 100.76 | q | 5954669628`
  `2026-08-31 21:59:42 | 5000 | 93.76 | 0.0 | -93.76 | 0.0 | ДАНС ХӨТӨЛСНИЙ ХУРААМЖ | (empty)`

## Business rules
1. **Dedupe**: `dedupe_hash = sha256("account_no|txn_time ISO seconds|amount 2dp|balance_after 2dp")`. Insert with `ON CONFLICT (dedupe_hash) DO NOTHING`. If the same file (sha256 of its bytes) is uploaded twice → `AlreadyImported`.
2. **Merchant key**: normalize description (uppercase; remove dates, times, masked cards, all digits, punctuation except `& . -`; drop noise words POS, MN, MNG, MONGOLIA, ULAANBAATAR, UB, УБ, УЛААНБААТАР, LLC, ХХК, XXK, PURCHASE, ХУДАЛДАН, АВАЛТ). If the result has ≥3 chars → key `DESC:<normalized>`, display `<normalized>.title()`. Otherwise, if there is a counterparty → `ACC:<counterparty>`, display `Account <counterparty>`. Otherwise `DESC:<normalized or UNKNOWN>`.
3. **Classification order** (first hit wins; `class_source='manual'` rows are never touched):
   1. merchant has `default_category_id` → source `merchant`
   2. active rules ordered by `priority, id` → source `rule`
   3. counterparty_account is in `accounts WHERE is_own` → category "Own-account transfer", source `own_account`
   4. else category NULL, source NULL
4. The statement's own account is upserted with `is_own=TRUE, has_statements=TRUE`.
5. Reports: income = SUM(amount) where kind='income'; expense = −SUM(amount) where kind='expense'; transfers are excluded.
6. Category label shown in the UI: `"<Kind> › <name>"`, e.g. `Expense › Groceries` (Kind = Income/Expense/Transfer).
