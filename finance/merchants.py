"""Turn a raw bank description into a stable 'merchant key' so the same shop groups together.

  'POS 2026.09.01 EMART HUNNU MALL 12345 ULAANBAATAR MN'  -> 'DESC:EMART HUNNU MALL'
  'q' + counterparty 5954669628                             -> 'ACC:5954669628'
"""
from __future__ import annotations

import re

# Words that add no meaning to a merchant name. Extend freely.
NOISE_WORDS = {
    "POS", "MN", "MNG", "MONGOLIA", "ULAANBAATAR", "UB", "УБ", "УЛААНБААТАР",
    "LLC", "ХХК", "XXK", "PURCHASE", "ХУДАЛДАН", "АВАЛТ",
}
MIN_MEANINGFUL_LEN = 3   # 'q', '1', 'ok' are not merchant names


def normalize(description: str | None) -> str:
    s = (description or "").upper()
    s = re.sub(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", " ", s)    # dates
    s = re.sub(r"\d{1,2}:\d{2}(:\d{2})?", " ", s)            # times
    s = re.sub(r"\d*[*X]{3,}\d*", " ", s)                    # masked card numbers
    s = re.sub(r"\d+", " ", s)                               # any other numbers
    s = re.sub(r"[^\w\s&.\-]", " ", s)                       # punctuation (keeps Cyrillic)
    s = s.replace("_", " ")
    words = [w.strip(".-") for w in s.split()]
    words = [w for w in words if w and w not in NOISE_WORDS]
    return " ".join(words)


def merchant_key(description: str | None, counterparty: str | None) -> tuple[str, str]:
    """Return (match_key, suggested display name)."""
    name = normalize(description)
    if len(name) >= MIN_MEANINGFUL_LEN:
        return f"DESC:{name}", name.title()
    if counterparty:
        return f"ACC:{counterparty}", f"Account {counterparty}"
    return f"DESC:{name or 'UNKNOWN'}", name or "Unknown"
