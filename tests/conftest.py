import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HEADER = ["Гүйлгээний огноо", "Салбар", "Эхний үлдэгдэл", "Кредит гүйлгээ", "Дебит гүйлгээ",
          "Эцсийн үлдэгдэл", "Гүйлгээний утга", "Харьцсан данс"]


def make_khan_xlsx(path: Path, rows: list[list], totals: tuple | None = None) -> Path:
    """Build a fake Khan Bank statement with the real layout (no personal data)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Deposit Account Statement"
    ws.append(["Хэвлэсэн огноо:", "10/14/2026", "Депозит дансны дэлгэрэнгүй хуулга", "Хэрэглэгч:", "TEST USER",
               "Интервал:", "2026/08/14", "-", "2026/10/14", "Валют:", "MNT", "IBAN: MN120005005000111222"])
    ws.append(HEADER)
    for r in rows:
        ws.append(r)
    ws.append([])
    ws.append([])
    if totals:
        ws.append(["Нийт дүн:", None, None, totals[0], totals[1]])
    wb.save(path)
    return path


SAMPLE_ROWS = [
    ["2026-08-21 12:53:59", "5941", 100.76, 150000.0, 0.0, 150100.76, "q", "5000999001"],
    ["2026-08-21 12:54:25", "5003", 150100.76, 0.0, -150000.0, 100.76, "q", "5000999002"],
    ["2026-08-25 10:00:00", "5003", 100.76, 0.0, -7.0, 93.76, "POS 2026.08.25 EMART HUNNU 1234 ULAANBAATAR MN", None],
    ["2026-08-31 21:59:42", "5000", 93.76, 0.0, -93.76, 0.0, "ДАНС ХӨТӨЛСНИЙ ХУРААМЖ", None],
]


@pytest.fixture
def khan_file(tmp_path):
    return make_khan_xlsx(tmp_path / "Statement_MNT_5000111222.xlsx", SAMPLE_ROWS, ("150000.00", "150100.76"))
