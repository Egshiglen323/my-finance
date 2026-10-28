"""Common types for every bank parser."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd


@dataclass
class Transaction:
    txn_time: datetime
    amount: Decimal                 # + money in, - money out
    balance_before: Decimal | None
    balance_after: Decimal | None
    description: str
    counterparty_account: str | None
    branch: str | None = None

    def dedupe_hash(self, account_no: str) -> str:
        """Same transaction in two overlapping statements -> same hash."""
        key = "|".join([
            account_no,
            self.txn_time.isoformat(timespec="seconds"),
            f"{self.amount:.2f}",
            "" if self.balance_after is None else f"{self.balance_after:.2f}",
        ])
        return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass
class Statement:
    bank_code: str
    bank_name: str
    account_no: str
    iban: str | None
    currency: str
    holder: str | None
    period_from: date | None
    period_to: date | None
    transactions: list[Transaction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class BankParser(ABC):
    """Implement one subclass per bank and register it in registry.py."""
    bank_code: str = ""
    bank_name: str = ""

    @abstractmethod
    def can_parse(self, grid: pd.DataFrame, file_name: str) -> bool:
        """Return True if this raw sheet looks like this bank's statement."""

    @abstractmethod
    def parse(self, grid: pd.DataFrame, file_name: str) -> Statement:
        """Turn the raw sheet (no header, all cells as objects) into a Statement."""


# ---------- small helpers shared by parsers ----------

def is_blank(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip())


def cell_str(v) -> str:
    if is_blank(v):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def to_decimal(v) -> Decimal | None:
    if is_blank(v):
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(v)).quantize(Decimal("0.01"))
    s = str(v).replace(",", "").replace(" ", "").replace(" ", "")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def to_datetime(v) -> datetime | None:
    if is_blank(v):
        return None
    if isinstance(v, datetime):
        return v.to_pydatetime() if isinstance(v, pd.Timestamp) else v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y.%m.%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None
