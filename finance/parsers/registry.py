"""Pick the right parser for an uploaded file. Add new banks to PARSERS."""
from __future__ import annotations

import io

import pandas as pd

from .base import BankParser, Statement
from .khanbank import KhanBankParser

PARSERS: list[BankParser] = [
    KhanBankParser(),
    # GolomtParser(), TDBParser(), ...   <- add later
]


def load_grid(data: bytes, file_name: str) -> pd.DataFrame:
    """Read the first sheet with no header and no type guessing."""
    name = file_name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(io.BytesIO(data), header=None, dtype=object)
    return pd.read_excel(io.BytesIO(data), header=None, dtype=object, sheet_name=0)


def parse_statement(data: bytes, file_name: str) -> Statement:
    grid = load_grid(data, file_name)
    for parser in PARSERS:
        if parser.can_parse(grid, file_name):
            return parser.parse(grid, file_name)
    raise ValueError(f"'{file_name}' does not match any known bank statement format.")
