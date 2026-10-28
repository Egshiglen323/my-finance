"""Khan Bank (Хаан банк) deposit account statement, .xlsx export from e-banking.

Layout (checked against a real export, 2026-10):
  row 1 : 'Хэвлэсэн огноо:' <date> 'Депозит дансны дэлгэрэнгүй хуулга' 'Хэрэглэгч:' <name>
          'Интервал:' <from> '-' <to> 'Валют:' <cur> 'IBAN: MN..0005..'
  row 2 : header  Гүйлгээний огноо | Салбар | Эхний үлдэгдэл | Кредит гүйлгээ |
                  Дебит гүйлгээ (negative) | Эцсийн үлдэгдэл | Гүйлгээний утга | Харьцсан данс
  rows  : transactions, then blank rows, then 'Нийт дүн:' totals row.
"""
from __future__ import annotations

import re
from decimal import Decimal

import pandas as pd

from .base import BankParser, Statement, Transaction, cell_str, is_blank, to_datetime, to_decimal

KHAN_BANK_CODE_IN_IBAN = "0005"

COLUMNS = {
    "Гүйлгээний огноо": "txn_time",
    "Салбар": "branch",
    "Эхний үлдэгдэл": "balance_before",
    "Кредит гүйлгээ": "credit",
    "Дебит гүйлгээ": "debit",
    "Эцсийн үлдэгдэл": "balance_after",
    "Гүйлгээний утга": "description",
    "Харьцсан данс": "counterparty",
}
REQUIRED = {"txn_time", "credit", "debit", "description"}


def _find_header_row(grid: pd.DataFrame) -> int | None:
    for i in range(min(20, len(grid))):
        values = {cell_str(v) for v in grid.iloc[i].tolist()}
        if "Гүйлгээний огноо" in values and "Гүйлгээний утга" in values:
            return i
    return None


class KhanBankParser(BankParser):
    bank_code = "KHAN"
    bank_name = "Khan Bank"

    def can_parse(self, grid, file_name):
        h = _find_header_row(grid)
        if h is None:
            return False
        top = " ".join(cell_str(v) for r in range(h) for v in grid.iloc[r].tolist())
        iban = re.search(r"MN\d{2}(\d{4})\d+", top)
        if iban:
            return iban.group(1) == KHAN_BANK_CODE_IN_IBAN
        return "Депозит дансны" in top

    # ---- metadata in the rows above the header ----
    @staticmethod
    def _metadata(grid, header_row, file_name):
        cells = [cell_str(v) for r in range(header_row) for v in grid.iloc[r].tolist()]
        meta = {"holder": None, "currency": "MNT", "iban": None, "from": None, "to": None}
        for i, c in enumerate(cells):
            nxt = cells[i + 1] if i + 1 < len(cells) else ""
            if c.startswith("Хэрэглэгч"):
                meta["holder"] = nxt or None
            elif c.startswith("Валют"):
                meta["currency"] = nxt or "MNT"
            elif c.startswith("IBAN"):
                meta["iban"] = c.split(":", 1)[-1].strip() or nxt
            elif c.startswith("Интервал"):
                rest = [x for x in cells[i + 1:i + 4] if x and x != "-"]
                if rest:
                    meta["from"] = to_datetime(rest[0])
                if len(rest) > 1:
                    meta["to"] = to_datetime(rest[1])
        account_no = None
        if meta["iban"]:
            digits = re.sub(r"\D", "", meta["iban"])
            account_no = digits[6:].lstrip("0") or None   # MN + 2 check + 4 bank code
        if not account_no:
            m = re.search(r"(\d{8,12})", file_name)
            account_no = m.group(1) if m else "UNKNOWN"
        return meta, account_no

    def parse(self, grid, file_name):
        h = _find_header_row(grid)
        if h is None:
            raise ValueError("Khan Bank header row not found")
        meta, account_no = self._metadata(grid, h, file_name)

        col_idx = {}
        for j, v in enumerate(grid.iloc[h].tolist()):
            name = COLUMNS.get(cell_str(v))
            if name:
                col_idx[name] = j
        missing = REQUIRED - col_idx.keys()
        if missing:
            raise ValueError(f"Khan Bank statement is missing columns: {sorted(missing)}")

        def get(row, name):
            j = col_idx.get(name)
            return None if j is None else row[j]

        txns: list[Transaction] = []
        totals = None
        for i in range(h + 1, len(grid)):
            row = grid.iloc[i].tolist()
            first = cell_str(row[col_idx["txn_time"]])
            if first.startswith("Нийт дүн"):
                totals = (to_decimal(get(row, "credit")), to_decimal(get(row, "debit")))
                continue
            ts = to_datetime(get(row, "txn_time"))
            if ts is None:
                continue   # blank / footer line
            credit = to_decimal(get(row, "credit")) or Decimal("0")
            debit = to_decimal(get(row, "debit")) or Decimal("0")
            cp = cell_str(get(row, "counterparty")) or None
            txns.append(Transaction(
                txn_time=ts,
                amount=abs(credit) - abs(debit),
                balance_before=to_decimal(get(row, "balance_before")),
                balance_after=to_decimal(get(row, "balance_after")),
                description=cell_str(get(row, "description")),
                counterparty_account=cp,
                branch=cell_str(get(row, "branch")) or None,
            ))

        stmt = Statement(
            bank_code=self.bank_code, bank_name=self.bank_name, account_no=account_no,
            iban=meta["iban"], currency=meta["currency"], holder=meta["holder"],
            period_from=meta["from"].date() if meta["from"] else None,
            period_to=meta["to"].date() if meta["to"] else None,
            transactions=txns,
        )
        stmt.warnings.extend(self._check(txns, totals))
        return stmt

    @staticmethod
    def _check(txns, totals) -> list[str]:
        warns = []
        prev = None
        for t in txns:
            if t.balance_before is not None and t.balance_after is not None:
                if t.balance_before + t.amount != t.balance_after:
                    warns.append(f"{t.txn_time}: balance {t.balance_before} + {t.amount} != {t.balance_after}")
            if prev is not None and prev.balance_after is not None and t.balance_before is not None:
                if prev.balance_after != t.balance_before:
                    warns.append(f"{t.txn_time}: opening balance {t.balance_before} does not follow "
                                 f"previous closing balance {prev.balance_after} (missing rows?)")
            prev = t
        if totals and totals[0] is not None and totals[1] is not None:
            credit = sum((t.amount for t in txns if t.amount > 0), Decimal("0"))
            debit = sum((-t.amount for t in txns if t.amount < 0), Decimal("0"))
            if credit != abs(totals[0]) or debit != abs(totals[1]):
                warns.append(f"Totals differ from the 'Нийт дүн' row: file says credit {totals[0]} / "
                             f"debit {totals[1]}, rows add up to {credit} / {debit}")
        return warns
