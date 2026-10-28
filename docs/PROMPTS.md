# Build prompts for free AI coding agents

Feed these **one at a time, in order**. Each prompt builds one small piece and ends with a test that must pass before you move on.

## Before you start (5 minutes)
1. Make an empty project folder and copy **everything in `starter/`** into it: `migrations/`, `tests/`, `requirements.txt`, `.env.example`, `.gitignore`, `.streamlit/`, `run.bat`, `run.sh`, `README.md`. Also copy `SPEC.md` to `docs/SPEC.md`.
2. Follow README steps 1–4: install PostgreSQL, create the `finance` database and user, create the venv, run `pip install -r requirements.txt`, and create `.env`. To run the database tests, also create an empty `finance_test` database and add `TEST_DATABASE_URL=...` to `.env`.
3. The agents never write SQL tables or tests. Those are provided, and the tests are the referee.

## How to save usage
- **Start a new chat for every prompt.** Old context wastes free-tier tokens and confuses the model.
- **IDE agents** (Copilot Chat agent mode in VS Code, Gemini Code Assist, Gemini CLI, Cursor free tier): open the project folder and paste the prompt as it is. The agent reads `docs/SPEC.md` and the listed files itself.
- **Web chats** (ChatGPT free, Gemini web, Claude free, DeepSeek): attach or paste `docs/SPEC.md` plus every file under **Attach** in that prompt, then the prompt. Save the code it returns into the named files yourself.
- **Prompts 3, 6, 8, 9 and 10 are the hardest.** Give them to the strongest model you have quota for. The others work on small or fast models.
- If a test fails, don't argue in a long thread. Use the **FIX prompt** at the bottom in a new chat.
- Run the check command after each step. Commit with git after each green step (`git init` once, then `git add -A && git commit -m "step N"`). Then a bad step can be undone with `git checkout .`.

---

## PROMPT 1 — database connection + migration runner
**Attach:** docs/SPEC.md, migrations/001_schema.sql
```
Read docs/SPEC.md. Create exactly 2 files: finance/__init__.py (empty) and finance/db.py.

finance/db.py must contain:
- ROOT = project root (Path(__file__).resolve().parent.parent); MIGRATIONS_DIR = ROOT / "migrations"
- load_dotenv(ROOT / ".env") at import time
- get_conn(url: str | None = None) -> psycopg.Connection
    url defaults to os.getenv("DATABASE_URL"); if missing raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and edit it.")
    return psycopg.connect(url, row_factory=dict_row, autocommit=True)
- migrate(conn) -> list[str]
    CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())
    for each migrations/*.sql in sorted order not yet in schema_migrations:
      inside `with conn.transaction():` execute the whole file text (utf-8) with conn.execute(text) and insert its name.
    return list of applied file names.
- if __name__ == "__main__": connect, migrate, print "Applied: a, b" or "Applied: nothing (already up to date)".

Use psycopg v3 only. Do not touch any other file. Output only the two files, no explanations.
```
**Check:** `python -m finance.db` prints `Applied: 001_schema.sql, 002_seed.sql`. Running it a second time prints `nothing`.

---

## PROMPT 2 — parser base types
**Attach:** docs/SPEC.md
```
Read docs/SPEC.md. Create only finance/parsers/base.py.

Contents:
1. @dataclass Transaction: txn_time: datetime; amount: Decimal; balance_before: Decimal | None; balance_after: Decimal | None; description: str; counterparty_account: str | None; branch: str | None = None
   method dedupe_hash(self, account_no: str) -> str = sha256 hex of "|".join([account_no, txn_time.isoformat(timespec="seconds"), f"{amount:.2f}", "" if balance_after is None else f"{balance_after:.2f}"]) utf-8.
2. @dataclass Statement: bank_code: str; bank_name: str; account_no: str; iban: str | None; currency: str; holder: str | None; period_from: date | None; period_to: date | None; transactions: list[Transaction] = field(default_factory=list); warnings: list[str] = field(default_factory=list)
3. class BankParser(ABC): bank_code = ""; bank_name = ""; abstract can_parse(self, grid: pd.DataFrame, file_name: str) -> bool; abstract parse(self, grid: pd.DataFrame, file_name: str) -> Statement
4. helpers:
   is_blank(v): None, NaN float, or whitespace-only str -> True
   cell_str(v): "" if blank; float with integer value -> str(int(v)); else str(v).strip()
   to_decimal(v): None if blank; int/float -> Decimal(str(v)).quantize(Decimal("0.01")); str -> remove "," spaces and   then Decimal quantized; invalid -> None
   to_datetime(v): None if blank; datetime (incl. pd.Timestamp -> .to_pydatetime()) returned; str tried with formats "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%m/%d/%Y"; else None
Output only the file.
```
**Check:** `python -c "from finance.parsers.base import to_decimal, to_datetime; print(to_decimal('1,536,091.76'), to_datetime('2026/08/14'))"` prints `1536091.76 2026-08-14 00:00:00`.
(`finance/parsers/__init__.py` doesn't exist yet. If the import fails, create an empty one for now. Prompt 3 replaces it.)

---

## PROMPT 3 — Khan Bank parser + registry  ★ use a strong model
**Attach:** docs/SPEC.md, finance/parsers/base.py, tests/conftest.py, tests/test_khanbank.py
```
Read docs/SPEC.md (section "Khan Bank statement format") and finance/parsers/base.py. Create 3 files:

A) finance/parsers/khanbank.py
- COLUMNS dict mapping the 8 Mongolian header names to: txn_time, branch, balance_before, credit, debit, balance_after, description, counterparty. REQUIRED = {"txn_time","credit","debit","description"}.
- _find_header_row(grid) -> int | None: first row index (search first 20 rows) whose cell_str values contain both "Гүйлгээний огноо" and "Гүйлгээний утга".
- class KhanBankParser(BankParser), bank_code "KHAN", bank_name "Khan Bank".
  can_parse: header row exists AND (if an IBAN pattern MN\d{2}(\d{4})\d+ is found in the text of rows above the header, bank code group == "0005"; otherwise "Депозит дансны" in that text).
  parse:
   * metadata from all cells above header (flattened list of cell_str): "Хэрэглэгч" -> next cell = holder; "Валют" -> next = currency (default MNT); cell starting "IBAN" -> text after ":"; "Интервал" -> next up to 3 cells, ignoring "-" and empty: from, to (to_datetime).
   * account_no = IBAN digits [6:] with leading zeros stripped; fallback: first 8-12 digit run in file_name; else "UNKNOWN".
   * map header columns by name; raise ValueError listing missing REQUIRED columns.
   * for each row after the header: if the txn_time cell text starts with "Нийт дүн" store totals=(to_decimal(credit), to_decimal(debit)) and continue; skip rows where to_datetime fails; amount = abs(credit) - abs(debit) (missing -> 0); counterparty = cell_str or None; branch = cell_str or None.
   * warnings (strings): per row if balance_before + amount != balance_after -> f"{time}: balance ..."; if previous balance_after != this balance_before -> message containing "missing rows"; if totals exist and sum of positive amounts != abs(totals[0]) or sum of -negative amounts != abs(totals[1]) -> message starting "Totals differ".
B) finance/parsers/registry.py
- PARSERS: list[BankParser] = [KhanBankParser()]
- load_grid(data: bytes, file_name: str) -> DataFrame: .csv -> pd.read_csv(BytesIO, header=None, dtype=object); else pd.read_excel(BytesIO, header=None, dtype=object, sheet_name=0)
- parse_statement(data, file_name) -> Statement: first parser whose can_parse is True; else raise ValueError(f"'{file_name}' does not match any known bank statement format.")
C) finance/parsers/__init__.py: `from .registry import parse_statement, PARSERS  # noqa: F401`

Do not edit tests. Output only the 3 files.
```
**Check:** `pytest tests/test_khanbank.py -q` → 5 passed.
**Real file check:** `python -c "from finance.parsers import parse_statement as p; s=p(open('YOUR_STATEMENT.xlsx','rb').read(),'Statement_MNT_5954230716.xlsx'); print(s.account_no, len(s.transactions), s.warnings)"` → `5954230716 63 []`.

---

## PROMPT 4 — merchant key
**Attach:** docs/SPEC.md, tests/test_merchants_classifier.py
```
Read docs/SPEC.md business rule 2. Create only finance/merchants.py with:
- NOISE_WORDS set (exactly the words listed in the spec), MIN_MEANINGFUL_LEN = 3
- normalize(description: str | None) -> str, steps in this order on the uppercased text:
  remove dates r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"; times r"\d{1,2}:\d{2}(:\d{2})?"; masked cards r"\d*[*X]{3,}\d*"; any digits r"\d+";
  replace r"[^\w\s&.\-]" with space; replace "_" with space; split on whitespace, strip ".-" from each word, drop empty and NOISE_WORDS; join with single spaces.
- merchant_key(description, counterparty) -> tuple[str, str] (match_key, display_name) exactly as in the spec.
Output only the file.
```
**Check:** `pytest tests/test_merchants_classifier.py -q -k "normalize or merchant_key"` → 2 passed.

---

## PROMPT 5 — classifier
**Attach:** docs/SPEC.md, tests/test_merchants_classifier.py
```
Read docs/SPEC.md business rule 3. Create only finance/classifier.py:
- @dataclass Rule: id: int; priority: int; field: str; op: str; value: str; direction: str | None; category_id: int
- rule_matches(rule, description, counterparty, amount: Decimal) -> bool
   direction "credit" requires amount > 0, "debit" requires amount < 0.
   field "amount": op "between" -> value "min,max" (either side may be empty), compare abs(amount) inclusive; any other op -> abs(amount) == Decimal(value); parse errors -> False.
   field "description"/"counterparty": text = that value or "". contains/equals are case-insensitive (equals also strips); regex uses re.search with re.IGNORECASE, invalid regex -> False.
- decide(txn: dict, rules, merchant_defaults: dict[int, int | None], own_accounts: set[str], own_category_id) -> (category_id, source) | (None, None) using the spec order. txn keys: merchant_id, description, counterparty_account, amount.
- load_rules(conn) -> list[Rule]: active rules ORDER BY priority, id.
- classify(conn, import_id: int | None = None) -> int
   load rules, merchant defaults {id: default_category_id}, own accounts (accounts.is_own), id of category kind='transfer' name='Own-account transfer'.
   select id, description, counterparty_account, amount, merchant_id, category_id, class_source from transactions WHERE class_source IS DISTINCT FROM 'manual' (+ AND import_id=%s if given).
   compute decide(); collect (cat, src, id) only where changed; executemany UPDATE inside `with conn.transaction(), conn.cursor() as cur:`. return number changed.
Output only the file.
```
**Check:** `pytest tests/test_merchants_classifier.py -q` → 4 passed.

---

## PROMPT 6 — importer  ★ use a strong model
**Attach:** docs/SPEC.md, finance/parsers/base.py, finance/merchants.py, finance/classifier.py, tests/test_import_db.py
```
Read docs/SPEC.md business rules 1, 2, 4. Create only finance/importer.py:
- class AlreadyImported(Exception)
- @dataclass ImportResult: import_id: int; statement: Statement; rows_read: int; rows_inserted: int; duplicates: int; classified: int; new_merchants: int
- file_hash(data: bytes) -> str (sha256 hex)
- preview(data, file_name) -> Statement  (just parse_statement, saves nothing)
- import_statement(conn, data: bytes, file_name: str) -> ImportResult
  1. if imports.file_sha256 already exists -> raise AlreadyImported(f"'{file_name}' was already imported.")
  2. stmt = parse_statement(...)
  3. inside ONE `with conn.transaction():`
     - upsert bank by code (ON CONFLICT (code) DO UPDATE SET name = banks.name RETURNING id)
     - upsert account by account_no with bank_id, iban, currency, holder, is_own TRUE, has_statements TRUE (keep existing iban/holder when new is NULL via COALESCE) RETURNING id
     - insert imports row (account_id, file_name, file_sha256, period_from, period_to, rows_read) RETURNING id
     - for each transaction: merchant_key(); cache key->merchant id in a dict; INSERT INTO merchants ... ON CONFLICT (match_key) DO NOTHING RETURNING id (count new ones), else SELECT id; INSERT transaction ... ON CONFLICT (dedupe_hash) DO NOTHING RETURNING id (count inserted)
     - UPDATE imports SET rows_inserted
  4. classified = classify(conn, import_id=...)
  5. return ImportResult (duplicates = rows_read - rows_inserted)
All SQL with %s params. Output only the file.
```
**Check:** `pytest tests/test_import_db.py -q` → 1 passed (it is skipped if `TEST_DATABASE_URL` isn't set).

---

## PROMPT 7 — repo.py (all queries for the UI)
**Attach:** docs/SPEC.md, finance/classifier.py, tests/test_repo_db.py
```
Read docs/SPEC.md. Create only finance/repo.py. Every function takes conn first and returns list[dict] / dict / None. Use %s params only.

KIND_LABEL = {"income":"Income","expense":"Expense","transfer":"Transfer"}
categories(conn): id,name,kind,sort_order ordered income, expense, transfer then sort_order, name
category_label(c) -> f"{KIND_LABEL[kind]} › {name}"
category_maps(conn) -> (id_to_label, label_to_id)
upsert_category(conn, cat_id|None, name, kind, sort_order=100): UPDATE if id else INSERT ... ON CONFLICT (kind,name) DO NOTHING
delete_category(conn, cat_id)
unclassified_merchants(conn): merchants with default_category_id NULL joined to their transactions with category_id NULL, grouped per merchant:
   id, match_key, display_name, txn_count, money_in (sum positive, 0 if none), money_out (positive number, 0 if none), first_seen, last_seen,
   samples = (ARRAY_AGG(DISTINCT description))[1:3], counterparties = first 3 distinct non-null counterparty accounts; order by txn_count desc, display_name
all_merchants(conn): id, match_key, display_name, default_category_id, txn_count, net_amount, last_seen (LEFT JOIN), order by display_name
update_merchant(conn, merchant_id, display_name|None, category_id|None): display_name=COALESCE(%s, display_name), default_category_id=%s
accounts(conn): id, account_no, nickname, is_own, has_statements, currency, holder, bank (banks.name) ; set_own_account(conn, account_no, is_own=True, nickname=None) upsert; update_account(conn, id, nickname, is_own); account_label(a)
transactions(conn, date_from=None, date_to=None, account_ids=None, category_ids=None, unclassified_only=False, search=None, direction=None, limit=5000):
   date_to is inclusive (txn_time < date_to + 1 day); search = ILIKE on description, counterparty_account, merchant display_name, note; direction "in" amount>0 / "out" amount<0; unclassified_only overrides category_ids.
   returns id, txn_time, account_no, amount, balance_after, description, counterparty_account, merchant (display_name), category_id, class_source, note ; order txn_time desc, id desc
set_transaction_category(conn, txn_id, category_id|None, note=None): class_source = 'manual' if category_id else NULL
set_note(conn, txn_id, note)
reset_to_auto(conn, txn_ids) -> int: set class_source NULL and category_id NULL for ids (= ANY(%s)), then return classifier.classify(conn)
rules(conn) ordered by priority,id ; replace_rules(conn, rows: list[dict]) delete all + insert inside one transaction
test_rule(conn, field, op, value, direction, limit=200): use classifier.rule_matches in Python over all transactions (id, txn_time, amount, description, counterparty_account)
monthly_summary(conn, date_from, date_to): month 'YYYY-MM', income, expense (positive), unclassified_net, unclassified_count
by_category(conn, date_from, date_to, kind): category, total (positive for expense), txn_count ordered by total desc
top_merchants(conn, date_from, date_to, limit=15): merchant, category, spent (positive), txn_count — debits whose category kind is expense or NULL
daily_balances(conn, date_from, date_to): last balance_after per account per day: day, account (nickname or account_no), balance — use DISTINCT ON
date_bounds(conn) -> (min date, max date) of txn_time
imports(conn): id, imported_at, file_name, account_no, period_from, period_to, rows_read, rows_inserted newest first
backup(database_url, out_dir: Path) -> Path: run pg_dump --no-owner -h -p -U -f out_dir/finance_YYYYmmdd_HHMMSS.sql <db>, password via PGPASSWORD env, check=True
Output only the file.
```
**Check:** `pytest -q` → all tests pass (14 when `TEST_DATABASE_URL` is set).

---

## PROMPT 8 — UI part 1: skeleton, Upload, Classify  ★ use a strong model
**Attach:** docs/SPEC.md, finance/repo.py (signatures are enough), finance/importer.py
```
Read docs/SPEC.md. Create app.py (Streamlit >= 1.40). Only these parts now; later prompts add more pages.

Helpers:
- st.set_page_config(page_title="My Finance", page_icon="💰", layout="wide")
- @st.cache_resource _connect(): get_conn() then migrate(); db(): reconnect (clear the cache) if conn.closed or conn.broken
- go(page) callback sets st.session_state.page; flash(msg, kind="success") stores the message in session_state; show_flash() pops it and shows it
- money(x) -> f"{float(x or 0):,.0f} ₮"
- date_range_input(label, default:(date,date), key) -> (from, to), handling partial selection
- data_bounds(conn) -> repo.date_bounds with fallback (today-90d, today)
- PAGES = ["Upload","Classify","Transactions","Merchants","Rules","Reports","Settings"]
- main(): connect (on error st.error + hint about .env and st.stop()); sidebar title; st.sidebar.radio("Page", PAGES, key="page") where Classify shows "(N)" pending merchants; dispatch to page_<name>(conn). Pages not written yet: show st.info("Coming soon").

page_upload(conn):
- st.file_uploader for xlsx/xls/csv, multiple files. For each file: preview() inside try (st.error on failure); a bordered container with metrics Bank, Account, Period, Transactions; first 10 warnings as st.warning; first 10 rows in st.dataframe.
- If file_hash is already in imports -> st.info("already imported"), else an "Import" button (key includes the hash) -> import_statement -> flash a summary (new rows, duplicates skipped, auto-classified, new merchants) -> st.rerun(). Catch AlreadyImported.
- Below: show_flash(); if any unclassified merchants -> st.info + button "Classify now →" (on_click=go, args=("Classify",)); then an "Import history" table from repo.imports.

page_classify(conn):
- If no unclassified merchants: st.success and return.
- One st.form. Per merchant, 3 columns: [name + match_key + sample descriptions] [count, money in/out, first→last date] [text_input display name, selectbox category with first option "— skip for now —" + all category labels, and ONLY for match_key starting "ACC:" a checkbox "This is MY account (money moving between my own accounts)"]. st.divider between merchants.
- On submit: if own is ticked -> repo.set_own_account(conn, match_key[4:], True, new name if changed); if a category is chosen or the name changed -> repo.update_merchant. Then classifier.classify(conn), flash a summary, st.rerun().
- Caption tip: merchants needing a different category each time should be skipped and set per transaction on the Transactions page.
Output only app.py.
```
**Check:** `streamlit run app.py`. Upload your statement → Import → the Classify page lists 3 accounts. Tick "my account" for your own ones and pick a category for the others → Save → the page shows "Everything is classified".

---

## PROMPT 9 — UI part 2: Transactions + Merchants
**Attach:** docs/SPEC.md, app.py, finance/repo.py (signatures)
```
Add page_transactions and page_merchants to the existing app.py and wire them into main(). Change nothing else.

page_transactions(conn):
- Filters: date range (default = data_bounds), multiselect accounts that have has_statements (format with repo.account_label), multiselect category labels, checkbox "Only unclassified", search text, radio direction all/in/out (horizontal).
- Build a DataFrame indexed by transaction id with columns: Select(bool), Date, Account, Amount(float), Description, Counterparty, Merchant, Category(label or ""), Source, Note.
- Metrics: rows, money in, money out.
- st.data_editor: Category = SelectboxColumn(options [""] + labels), Amount NumberColumn format "%.2f", Date DatetimeColumn "YYYY-MM-DD HH:mm"; only Select, Category, Note editable; hide_index=True.
- Button "Save edits": compare to the original; a changed Category -> repo.set_transaction_category(id, label_to_id.get(label), note); a changed Note only -> repo.set_note. Then flash + rerun.
- Bulk actions on rows where Select is ticked: selectbox of category + button "Apply to N selected" (manual category), button "Back to automatic" -> repo.reset_to_auto.
- Download buttons: CSV (utf-8-sig) and Excel (pandas ExcelWriter, openpyxl) of the current rows without Select.

page_merchants(conn):
- Filter text box. data_editor indexed by merchant id: Name (editable), Match key, Default category (SelectboxColumn, editable), Transactions, Net amount, Last seen.
- Save -> repo.update_merchant for changed rows -> classify(conn) -> flash "Updated X merchants; Y transactions re-classified" -> rerun.
Output the full updated app.py.
```
**Check:** On the Transactions page, change one row's category and press Save. Its Source becomes `manual`. Tick it and press "Back to automatic", and the Source returns to an automatic one.

---

## PROMPT 10 — UI part 3: Rules, Reports, Settings
**Attach:** docs/SPEC.md, app.py, finance/repo.py (signatures)
```
Add page_rules, page_reports, page_settings to the existing app.py and wire them into main(). Change nothing else.

page_rules(conn):
- Markdown explaining the order: merchant default -> rules (lowest priority first) -> own account; manual is never overwritten; fields/ops list.
- data_editor(num_rows="dynamic") with columns Priority(Number, default 100), Field(Selectbox description/counterparty/amount), Op(Selectbox contains/equals/regex/between), Value, Direction(Selectbox any/credit/debit, default any), Category(Selectbox labels), Active(Checkbox default True), Note.
- "Save rules & re-classify": validate (field, op, value, category required -> st.error per bad row, save nothing), direction "any" -> None, repo.replace_rules, classify, flash, rerun.
- "Test a rule" form: field/op/value/direction -> repo.test_rule -> count + table.

page_reports(conn):
- Period date range; default from = first day of the month about 5 months before the last data date (not earlier than the first data date).
- Metrics: Income, Expense, Net, Unclassified rows (+ button to Classify if > 0). Caption: transfers are excluded.
- st.bar_chart of monthly income vs expense (stack=False).
- Two columns: expenses by category (horizontal bar chart + table) | income by category table + top merchants table. Convert Decimals to float.
- "Balance over time": daily_balances pivot day x account, ffill, st.line_chart.

page_settings(conn):
- Categories data_editor (dynamic rows, hidden id column, Kind selectbox, Name, Order). Save: upsert each row, delete categories whose id was removed, classify, flash.
- Accounts data_editor (Nickname and Own editable) + text input to add another own account number; Save -> update_account / set_own_account, classify, flash.
- Buttons: "Re-run automatic classification"; "Back up database now" -> repo.backup(os.environ["DATABASE_URL"], ROOT/"backups"); FileNotFoundError -> st.error("pg_dump was not found. Add PostgreSQL's bin folder to PATH").
Output the full updated app.py.
```
**Check:** every page opens without errors. Reports shows charts. Settings → Back up creates a file in `backups/`.

---

## FIX prompt (use in a new chat whenever a check fails)
**Attach:** docs/SPEC.md, the failing file, the test file
```
This file must make the test pass without changing the test or the spec. Here is the exact error:
<paste the last 30 lines of the pytest / streamlit error>
Find the root cause, fix it with the smallest change, and output only the corrected full file. No explanations.
```

## Later: add a new bank (one prompt)
**Attach:** docs/SPEC.md, finance/parsers/base.py, finance/parsers/khanbank.py, finance/parsers/registry.py, plus 5–10 anonymized rows and the header copied from the new bank's statement
```
Add a parser for <BANK NAME>, following khanbank.py's style. The statement layout is below. Create finance/parsers/<bank>.py with class <Bank>Parser(BankParser) (bank_code "<CODE>"), register it in PARSERS in registry.py, and create migrations/003_<bank>.sql with INSERT INTO banks (code, name) VALUES ('<CODE>', '<Name>') ON CONFLICT DO NOTHING; Also add tests/test_<bank>.py that builds a fake file with openpyxl, like tests/conftest.py does. Output only the new and changed files.
<paste layout + sample rows>
```
