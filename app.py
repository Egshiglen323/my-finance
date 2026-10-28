"""Personal finance tool - run with:  streamlit run app.py"""
from __future__ import annotations

import io
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from finance import repo
from finance.classifier import classify
from finance.db import ROOT, get_conn, migrate
from finance.importer import AlreadyImported, file_hash, import_statement, preview

st.set_page_config(page_title="My Finance", page_icon="💰", layout="wide")

PAGES = ["Upload", "Classify", "Transactions", "Merchants", "Rules", "Reports", "Settings"]
NONE_LABEL = ""
SKIP_LABEL = "— skip for now —"


# ---------------------------------------------------------------- helpers
@st.cache_resource
def _connect():
    c = get_conn()
    migrate(c)
    return c


def db():
    c = _connect()
    if c.closed or c.broken:
        _connect.clear()
        c = _connect()
    return c


def go(page: str):
    st.session_state.page = page


def flash(msg: str, kind: str = "success"):
    st.session_state.flash = (kind, msg)


def show_flash():
    if "flash" in st.session_state:
        kind, msg = st.session_state.pop("flash")
        getattr(st, kind)(msg)


def money(x) -> str:
    return f"{float(x or 0):,.0f} ₮"


def date_range_input(label: str, default: tuple[date, date], key: str) -> tuple[date, date]:
    v = st.date_input(label, value=default, key=key)
    if isinstance(v, (list, tuple)):
        if len(v) == 2:
            return v[0], v[1]
        if len(v) == 1:
            return v[0], v[0]
        return default
    return v, v


def data_bounds(conn) -> tuple[date, date]:
    lo, hi = repo.date_bounds(conn)
    today = date.today()
    return lo or today - timedelta(days=90), hi or today


def to_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Transactions")
    return buf.getvalue()


# ---------------------------------------------------------------- pages
def page_upload(conn):
    st.header("Upload bank statement")
    st.caption("Khan Bank: e-banking → Account statement → Excel. Overlapping periods are fine — "
               "transactions already stored are skipped.")
    files = st.file_uploader("Statement file(s)", type=["xlsx", "xls", "csv"], accept_multiple_files=True)
    done_hashes = {r["file_sha256"] for r in conn.execute("SELECT file_sha256 FROM imports").fetchall()}

    for f in files or []:
        data = f.getvalue()
        sha = file_hash(data)
        with st.container(border=True):
            st.subheader(f.name)
            try:
                s = preview(data, f.name)
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not read this file: {e}")
                continue
            c = st.columns(4)
            c[0].metric("Bank", s.bank_name)
            c[1].metric("Account", s.account_no)
            c[2].metric("Period", f"{s.period_from or '?'} → {s.period_to or '?'}")
            c[3].metric("Transactions", len(s.transactions))
            for w in s.warnings[:10]:
                st.warning(w)
            if len(s.warnings) > 10:
                st.warning(f"... and {len(s.warnings) - 10} more warnings")
            st.dataframe(pd.DataFrame([{
                "Date": t.txn_time, "Amount": float(t.amount), "Balance": float(t.balance_after or 0),
                "Description": t.description, "Counterparty": t.counterparty_account,
            } for t in s.transactions[:10]]), hide_index=True, use_container_width=True)

            if sha in done_hashes:
                st.info("This exact file is already imported.")
            elif st.button("Import", key=f"imp_{sha}", type="primary"):
                try:
                    r = import_statement(conn, data, f.name)
                except AlreadyImported as e:
                    st.info(str(e))
                else:
                    flash(f"{f.name}: {r.rows_inserted} new transactions saved, {r.duplicates} duplicates skipped, "
                          f"{r.classified} classified automatically, {r.new_merchants} new merchants.")
                    st.rerun()

    show_flash()
    pending = repo.unclassified_merchants(conn)
    if pending:
        st.info(f"**{len(pending)} merchants** need a category.")
        st.button("Classify now →", on_click=go, args=("Classify",), type="primary")

    st.subheader("Import history")
    hist = repo.imports(conn)
    if hist:
        st.dataframe(pd.DataFrame(hist).drop(columns=["id"]), hide_index=True, use_container_width=True)
    else:
        st.caption("Nothing imported yet.")


def page_classify(conn):
    st.header("Classify merchants")
    st.caption("Each row groups transactions with the same merchant name (or the same counterparty account "
               "when the description is meaningless, like 'q'). The category you pick is remembered and used "
               "automatically for future uploads.")
    show_flash()
    merchants = repo.unclassified_merchants(conn)
    if not merchants:
        st.success("Everything is classified. 🎉")
        return

    _, l2id = repo.category_maps(conn)
    options = [SKIP_LABEL] + list(l2id)
    choices = {}
    with st.form("classify_form"):
        for m in merchants:
            c1, c2, c3 = st.columns([3, 2, 4])
            c1.markdown(f"**{m['display_name']}**")
            c1.caption(f"`{m['match_key']}`  ·  examples: " + ", ".join(f"“{s}”" for s in (m["samples"] or [])))
            c2.markdown(f"{m['txn_count']} transactions  \n⬇ in {money(m['money_in'])}  \n⬆ out {money(m['money_out'])}")
            c2.caption(f"{m['first_seen']:%Y-%m-%d} → {m['last_seen']:%Y-%m-%d}")
            name = c3.text_input("Display name", m["display_name"], key=f"name_{m['id']}")
            cat = c3.selectbox("Category", options, key=f"cat_{m['id']}")
            own = False
            if m["match_key"].startswith("ACC:"):
                own = c3.checkbox("This is MY account (money moving between my own accounts)",
                                  key=f"own_{m['id']}")
            choices[m["id"]] = (m, name.strip(), cat, own)
            st.divider()
        submitted = st.form_submit_button("Save", type="primary")

    st.caption("Tip: if one merchant needs different categories each time (e.g. a person who sometimes "
               "pays you back and sometimes gives a gift), skip it here and set each transaction on the "
               "Transactions page.")

    if submitted:
        saved = 0
        for mid, (m, name, cat, own) in choices.items():
            cat_id = l2id.get(cat)
            if own:
                cat_id = None   # own account always means 'Own-account transfer'
                repo.set_own_account(conn, m["match_key"][4:], True,
                                     name if name and name != m["display_name"] else None)
                saved += 1
            if cat_id or (name and name != m["display_name"]):
                repo.update_merchant(conn, mid, name or None, cat_id)
                saved += 1 if cat_id else 0
        changed = classify(conn)
        flash(f"Saved {saved} choices; {changed} transactions updated.")
        st.rerun()


def page_transactions(conn):
    st.header("Transactions")
    show_flash()
    id2l, l2id = repo.category_maps(conn)
    accts = repo.accounts(conn)
    stmt_accts = [a for a in accts if a["has_statements"]]

    f1, f2, f3 = st.columns([2, 2, 2])
    lo, hi = data_bounds(conn)
    d_from, d_to = date_range_input("Dates", (lo, hi), "tx_dates")
    with f1:
        acct_sel = st.multiselect("Account", stmt_accts, format_func=repo.account_label)
    with f2:
        cat_sel = st.multiselect("Category", list(l2id))
        unclassified_only = st.checkbox("Only unclassified")
    with f3:
        search = st.text_input("Search (description, merchant, account, note)")
        direction = st.radio("Direction", ["all", "in", "out"], horizontal=True)

    rows = repo.transactions(
        conn, d_from, d_to, [a["id"] for a in acct_sel], [l2id[c] for c in cat_sel],
        unclassified_only, search or None, None if direction == "all" else direction)
    if not rows:
        st.info("No transactions match.")
        return

    df = pd.DataFrame([{
        "id": r["id"], "Select": False, "Date": r["txn_time"], "Account": r["account_no"],
        "Amount": float(r["amount"]), "Description": r["description"], "Counterparty": r["counterparty_account"],
        "Merchant": r["merchant"], "Category": id2l.get(r["category_id"], NONE_LABEL),
        "Source": r["class_source"] or "", "Note": r["note"] or "",
    } for r in rows]).set_index("id")

    inflow, outflow = df.Amount[df.Amount > 0].sum(), -df.Amount[df.Amount < 0].sum()
    m = st.columns(3)
    m[0].metric("Rows", len(df))
    m[1].metric("Money in", money(inflow))
    m[2].metric("Money out", money(outflow))

    edited = st.data_editor(
        df, key="tx_editor", hide_index=True, use_container_width=True, height=520,
        column_config={
            "Select": st.column_config.CheckboxColumn(width="small"),
            "Date": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            "Amount": st.column_config.NumberColumn(format="%.2f"),
            "Category": st.column_config.SelectboxColumn(options=[NONE_LABEL] + list(l2id), width="medium"),
            "Source": st.column_config.TextColumn(help="merchant / rule / own_account = automatic; manual = you"),
        },
        disabled=["Date", "Account", "Amount", "Description", "Counterparty", "Merchant", "Source"],
    )

    c1, c2, c3, c4 = st.columns([1, 2, 1, 1])
    if c1.button("Save edits", type="primary"):
        n = 0
        for tid, new in edited.iterrows():
            old = df.loc[tid]
            if new["Category"] != old["Category"]:
                repo.set_transaction_category(conn, int(tid), l2id.get(new["Category"]), new["Note"] or None)
                n += 1
            elif new["Note"] != old["Note"]:
                repo.set_note(conn, int(tid), new["Note"] or None)
                n += 1
        flash(f"Saved {n} changes.")
        st.rerun()

    selected = [int(i) for i in edited.index[edited["Select"]]]
    bulk_cat = c2.selectbox("Set category for selected rows", list(l2id), label_visibility="collapsed")
    if c3.button(f"Apply to {len(selected)} selected", disabled=not selected):
        for tid in selected:
            repo.set_transaction_category(conn, tid, l2id[bulk_cat], df.loc[tid, "Note"] or None)
        flash(f"{len(selected)} transactions set to {bulk_cat}.")
        st.rerun()
    if c4.button("Back to automatic", disabled=not selected,
                 help="Remove the manual category and let merchant/rules decide again"):
        repo.reset_to_auto(conn, selected)
        flash(f"{len(selected)} transactions returned to automatic classification.")
        st.rerun()

    out = edited.drop(columns=["Select"]).reset_index(drop=True)
    e1, e2, _ = st.columns([1, 1, 4])
    e1.download_button("⬇ CSV", out.to_csv(index=False).encode("utf-8-sig"), "transactions.csv", "text/csv")
    e2.download_button("⬇ Excel", to_excel(out), "transactions.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def page_merchants(conn):
    st.header("Merchants")
    st.caption("Rename merchants or change the category they get by default. Saving re-classifies every "
               "non-manual transaction.")
    show_flash()
    id2l, l2id = repo.category_maps(conn)
    ms = repo.all_merchants(conn)
    if not ms:
        st.info("No merchants yet — upload a statement first.")
        return
    df = pd.DataFrame([{
        "id": m["id"], "Name": m["display_name"], "Match key": m["match_key"],
        "Default category": id2l.get(m["default_category_id"], NONE_LABEL),
        "Transactions": m["txn_count"], "Net amount": float(m["net_amount"]), "Last seen": m["last_seen"],
    } for m in ms]).set_index("id")
    search = st.text_input("Filter")
    view = df[df["Name"].str.contains(search, case=False) | df["Match key"].str.contains(search, case=False)] \
        if search else df
    edited = st.data_editor(
        view, hide_index=True, use_container_width=True, height=560, key="merch_editor",
        column_config={
            "Default category": st.column_config.SelectboxColumn(options=[NONE_LABEL] + list(l2id)),
            "Net amount": st.column_config.NumberColumn(format="%.2f"),
            "Last seen": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
        },
        disabled=["Match key", "Transactions", "Net amount", "Last seen"],
    )
    if st.button("Save", type="primary"):
        n = 0
        for mid, new in edited.iterrows():
            old = view.loc[mid]
            if new["Name"] != old["Name"] or new["Default category"] != old["Default category"]:
                repo.update_merchant(conn, int(mid), new["Name"] or None, l2id.get(new["Default category"]))
                n += 1
        changed = classify(conn)
        flash(f"Updated {n} merchants; {changed} transactions re-classified.")
        st.rerun()


def page_rules(conn):
    st.header("Rules")
    st.markdown(
        "Rules classify transactions automatically. Order of checks for each transaction:\n"
        "1. **Merchant default** (set on Classify / Merchants)\n"
        "2. **Rules** — lowest *priority* number first, first match wins\n"
        "3. **Own account** — counterparty is one of your accounts → *Own-account transfer*\n\n"
        "Manual choices are never overwritten. Fields: `description`, `counterparty` (account number), "
        "`amount`. Ops: `contains`, `equals`, `regex`, `between` (amount only, value like `10000,50000`).")
    show_flash()
    id2l, l2id = repo.category_maps(conn)
    rs = repo.rules(conn)
    df = pd.DataFrame([{
        "Priority": r["priority"], "Field": r["field"], "Op": r["op"], "Value": r["value"],
        "Direction": r["direction"] or "any", "Category": id2l.get(r["category_id"], NONE_LABEL),
        "Active": r["active"], "Note": r["note"] or "",
    } for r in rs], columns=["Priority", "Field", "Op", "Value", "Direction", "Category", "Active", "Note"])
    edited = st.data_editor(
        df, num_rows="dynamic", hide_index=True, use_container_width=True, key="rules_editor",
        column_config={
            "Priority": st.column_config.NumberColumn(min_value=0, step=1, default=100),
            "Field": st.column_config.SelectboxColumn(options=["description", "counterparty", "amount"], required=True),
            "Op": st.column_config.SelectboxColumn(options=["contains", "equals", "regex", "between"], required=True),
            "Direction": st.column_config.SelectboxColumn(options=["any", "credit", "debit"], default="any"),
            "Category": st.column_config.SelectboxColumn(options=list(l2id), required=True),
            "Active": st.column_config.CheckboxColumn(default=True),
        })
    if st.button("Save rules & re-classify", type="primary"):
        rows, errors = [], []
        for i, r in edited.iterrows():
            if not r["Field"] or not r["Op"] or not str(r["Value"] or "").strip() or r["Category"] not in l2id:
                errors.append(f"Row {i + 1}: field, op, value and category are required")
                continue
            rows.append({"priority": int(r["Priority"] if pd.notna(r["Priority"]) else 100),
                         "field": r["Field"], "op": r["Op"], "value": str(r["Value"]).strip(),
                         "direction": None if r["Direction"] in (None, "any") else r["Direction"],
                         "category_id": l2id[r["Category"]], "active": bool(r["Active"]) if pd.notna(r["Active"]) else True,
                         "note": r["Note"] or None})
        if errors:
            for e in errors:
                st.error(e)
        else:
            repo.replace_rules(conn, rows)
            flash(f"Saved {len(rows)} rules; {classify(conn)} transactions re-classified.")
            st.rerun()

    st.subheader("Test a rule")
    with st.form("test_rule"):
        c = st.columns([2, 2, 3, 2])
        field = c[0].selectbox("Field", ["description", "counterparty", "amount"])
        op = c[1].selectbox("Op", ["contains", "equals", "regex", "between"])
        value = c[2].text_input("Value")
        direction = c[3].selectbox("Direction", ["any", "credit", "debit"])
        if st.form_submit_button("Show matches") and value:
            hits = repo.test_rule(conn, field, op, value, None if direction == "any" else direction)
            st.write(f"{len(hits)} matching transactions")
            if hits:
                st.dataframe(pd.DataFrame(hits).drop(columns=["id"]), hide_index=True, use_container_width=True)


def page_reports(conn):
    st.header("Reports")
    lo, hi = data_bounds(conn)
    default_from = max(lo, (hi.replace(day=1) - timedelta(days=150)).replace(day=1))
    d_from, d_to = date_range_input("Period", (default_from, hi), "rep_dates")

    monthly = repo.monthly_summary(conn, d_from, d_to)
    if not monthly:
        st.info("No data in this period.")
        return
    mdf = pd.DataFrame(monthly)
    for col in ("income", "expense", "unclassified_net"):
        mdf[col] = mdf[col].astype(float)
    income, expense = mdf.income.sum(), mdf.expense.sum()
    k = st.columns(4)
    k[0].metric("Income", money(income))
    k[1].metric("Expense", money(expense))
    k[2].metric("Net", money(income - expense))
    k[3].metric("Unclassified rows", int(mdf.unclassified_count.sum()))
    if mdf.unclassified_count.sum():
        st.button("Classify them →", on_click=go, args=("Classify",))
    st.caption("Transfers between your own accounts and cash withdrawals are excluded from income and expense.")

    st.subheader("Income vs expense by month")
    st.bar_chart(mdf.set_index("month")[["income", "expense"]].rename(columns=str.title), stack=False)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Expenses by category")
        exp = pd.DataFrame(repo.by_category(conn, d_from, d_to, "expense"))
        if not exp.empty:
            exp["total"] = exp["total"].astype(float)
            st.bar_chart(exp.set_index("category")["total"], horizontal=True)
            st.dataframe(exp, hide_index=True, use_container_width=True,
                         column_config={"total": st.column_config.NumberColumn("Total", format="%.0f")})
        else:
            st.caption("No classified expenses.")
    with c2:
        st.subheader("Income by category")
        inc = pd.DataFrame(repo.by_category(conn, d_from, d_to, "income"))
        if not inc.empty:
            inc["total"] = inc["total"].astype(float)
            st.dataframe(inc, hide_index=True, use_container_width=True,
                         column_config={"total": st.column_config.NumberColumn("Total", format="%.0f")})
        else:
            st.caption("No classified income.")
        st.subheader("Top merchants (spending)")
        top = pd.DataFrame(repo.top_merchants(conn, d_from, d_to))
        if not top.empty:
            top["spent"] = top["spent"].astype(float)
            st.dataframe(top, hide_index=True, use_container_width=True,
                         column_config={"spent": st.column_config.NumberColumn("Spent", format="%.0f")})

    st.subheader("Balance over time")
    bal = pd.DataFrame(repo.daily_balances(conn, d_from, d_to))
    if not bal.empty:
        bal["balance"] = bal["balance"].astype(float)
        st.line_chart(bal.pivot(index="day", columns="account", values="balance").ffill())


def page_settings(conn):
    st.header("Settings")
    show_flash()

    st.subheader("Categories")
    cats = repo.categories(conn)
    cdf = pd.DataFrame([{"id": c["id"], "Kind": c["kind"], "Name": c["name"], "Order": c["sort_order"]}
                        for c in cats], columns=["id", "Kind", "Name", "Order"])
    edited = st.data_editor(
        cdf, num_rows="dynamic", hide_index=True, use_container_width=True, key="cat_editor",
        column_config={
            "id": None,
            "Kind": st.column_config.SelectboxColumn(options=["income", "expense", "transfer"], required=True),
            "Order": st.column_config.NumberColumn(default=100, step=1),
        })
    st.caption("Deleting a category sends its transactions back to automatic classification and also deletes "
               "the rules that use it. *Transfer › Own-account transfer* can't be renamed or deleted.")
    if st.button("Save categories", type="primary"):
        own = next((c for c in cats if c["kind"] == "transfer" and c["name"] == "Own-account transfer"), None)
        keep, notes = set(), []
        for _, r in edited.iterrows():
            if not str(r["Name"] or "").strip() or not r["Kind"]:
                continue
            cid = int(r["id"]) if pd.notna(r.get("id")) else None
            order = int(r["Order"]) if pd.notna(r["Order"]) else 100
            name, kind = str(r["Name"]).strip(), r["Kind"]
            if own and cid == own["id"] and (name, kind) != (own["name"], own["kind"]):
                name, kind = own["name"], own["kind"]
                notes.append("'Own-account transfer' was kept as it is.")
            repo.upsert_category(conn, cid, name, kind, order)
            if cid:
                keep.add(cid)
        rules_removed = 0
        for c in cats:
            if c["id"] in keep:
                continue
            if own and c["id"] == own["id"]:
                notes.append("'Own-account transfer' can't be deleted.")
                continue
            rules_removed += repo.delete_category(conn, c["id"])
        if rules_removed:
            notes.append(f"{rules_removed} rule(s) using deleted categories were removed.")
        flash(" ".join(["Categories saved;", f"{classify(conn)} transactions re-classified."] + notes),
              "warning" if notes else "success")
        st.rerun()

    st.subheader("Accounts")
    st.caption("Accounts marked **own** are treated as transfers (not income/expense) when they appear as the "
               "counterparty.")
    accts = repo.accounts(conn)
    if accts:
        adf = pd.DataFrame([{"id": a["id"], "Account": a["account_no"], "Bank": a["bank"] or "",
                             "Nickname": a["nickname"] or "", "Own": a["is_own"],
                             "Statements imported": a["has_statements"]} for a in accts]).set_index("id")
        aed = st.data_editor(adf, hide_index=True, use_container_width=True, key="acct_editor",
                             disabled=["Account", "Bank", "Statements imported"])
        new_acct = st.text_input("Add another account number of yours (e.g. savings at another bank)")
        if st.button("Save accounts"):
            for aid, r in aed.iterrows():
                repo.update_account(conn, int(aid), r["Nickname"] or None, bool(r["Own"]))
            if new_acct.strip():
                repo.set_own_account(conn, new_acct.strip(), True)
            flash(f"Accounts saved; {classify(conn)} transactions re-classified.")
            st.rerun()

    st.subheader("Maintenance")
    c1, c2 = st.columns(2)
    if c1.button("Re-run automatic classification"):
        flash(f"{classify(conn)} transactions updated.")
        st.rerun()
    if c2.button("Back up database now"):
        try:
            path = repo.backup(os.environ["DATABASE_URL"], ROOT / "backups")
            st.success(f"Backup written to {path}")
        except FileNotFoundError:
            st.error("pg_dump was not found. Add PostgreSQL's bin folder to PATH (see README).")
        except Exception as e:  # noqa: BLE001
            st.error(f"Backup failed: {e}")


# ---------------------------------------------------------------- main
def main():
    try:
        conn = db()
    except Exception as e:  # noqa: BLE001
        st.error(f"Cannot connect to PostgreSQL: {e}")
        st.info("Check that PostgreSQL is running and DATABASE_URL in the .env file is correct.")
        st.stop()

    if "page" not in st.session_state:
        st.session_state.page = "Upload"
    pending = len(repo.unclassified_merchants(conn))
    st.sidebar.title("💰 My Finance")
    st.sidebar.radio("Page", PAGES, key="page",
                     format_func=lambda p: f"{p} ({pending})" if p == "Classify" and pending else p)

    {"Upload": page_upload, "Classify": page_classify, "Transactions": page_transactions,
     "Merchants": page_merchants, "Rules": page_rules, "Reports": page_reports,
     "Settings": page_settings}[st.session_state.page](conn)


main()
