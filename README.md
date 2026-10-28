# My Finance — personal finance tool (Khan Bank)

A local app for your own PC. You upload a bank statement (Excel), it stores the transactions in PostgreSQL, sorts them into income, expense or transfer automatically, and asks you to classify merchants it hasn't seen before.

- Python 3.10+ · PostgreSQL 14+ · Streamlit UI at http://localhost:8501
- Only you, only this PC (the app listens on `localhost` only).

---

## Setup (Windows, one click) — Монгол заавар: `ЗААВАР.md`

1. Install **Python** from https://www.python.org/downloads/ and tick **"Add python.exe to PATH"**.
2. Install **PostgreSQL** from https://www.postgresql.org/download/windows/. Remember the `postgres` password you choose. Keep port 5432.
3. Unzip this folder and double-click **`setup.bat`**. Press Enter for host and port, then type the `postgres` password. It installs the packages, creates the `finance` database and user (with its own random password), writes `.env` and creates the tables.
4. Double-click **`run.bat`** whenever you want to use the app. The browser opens http://localhost:8501.

Mac/Linux: `./setup.sh`, then `./run.sh`.
Manual setup instead: create the database yourself, copy `.env.example` to `.env`, then `pip install -r requirements.txt && python -m finance.db`.

---

## Day-to-day use

1. **Upload**: In Khan Bank e-banking, export the statement as Excel and drop it here. Check the summary, then press **Import**. Periods that overlap an earlier upload are fine, because transactions you already have are skipped.
2. **Classify** (the sidebar shows how many are waiting): each new merchant is listed once with its totals and example descriptions. Pick a category. For a counterparty that is another account of yours, tick **"This is MY account"**. Your choices are remembered for future uploads.
3. **Transactions**: filter, search, change any category by hand (manual choices are never overwritten), bulk-edit the selected rows, and export to CSV or Excel.
4. **Merchants / Rules**: rename merchants, change their default category, and add rules (e.g. *description contains "UNITEL" → Mobile & subscriptions*).
5. **Reports**: income vs expense by month, spending by category, top merchants, balance over time.
6. **Settings**: edit categories, name your accounts, back up the database (`pg_dump` → `backups/`).

### How automatic classification decides (first match wins)
1. **Merchant default**: the category you picked for that merchant.
2. **Rules**: checked from the lowest priority number up.
3. **Own account**: if the counterparty is one of your accounts, the row becomes *Own-account transfer*. Transfers are not counted as income or expense.
4. Otherwise the transaction is left unclassified and shows up on **Classify**.

When an account becomes one of yours (you tick "This is MY account", mark it Own in Settings, or upload its statement), the default category of its `Account <number>` merchant is cleared, so its rows become *Own-account transfer*. After every upload all transactions are re-checked, not only the new ones.

Manual choices on the Transactions page always win. Use **Back to automatic** to undo one.

### About your current statement
The account `…0716` statement is a pass-through account. Money arrives from `5954114905` / `5250449237` and leaves within a minute to `5954669628`, with descriptions like `q`. Because of that, merchants are grouped by **counterparty account**. Mark your own accounts so these rows aren't counted twice. Real shop purchases (POS) will appear when you upload the statement of the card account they're paid from.

---

## Tests
```
pytest                         # parser, merchants, classifier
```
To also test the database import, create an empty `finance_test` database, set `TEST_DATABASE_URL` in `.env` or in your environment, then run `pytest` again. (That database is wiped by the test.)

## Adding another bank later
1. Create `finance/parsers/<bank>.py` with a class that inherits `BankParser`, and implement `can_parse()` and `parse()` (copy `khanbank.py` as a template).
2. Add it to `PARSERS` in `finance/parsers/registry.py`.
3. Add `INSERT INTO banks ...` in a new migration file `migrations/003_<bank>.sql`.
Nothing else changes.

## Project layout
```
app.py                     Streamlit UI (all pages)
finance/db.py              connection + migration runner
finance/parsers/           base.py, khanbank.py, registry.py
finance/merchants.py       description -> merchant key
finance/classifier.py      rules / merchant / own-account logic
finance/importer.py        parse -> dedupe -> store -> classify
finance/repo.py            all SQL used by the UI, reports, backup
migrations/                001_schema.sql, 002_seed.sql
tests/                     pytest tests (synthetic statements, no personal data)
```
