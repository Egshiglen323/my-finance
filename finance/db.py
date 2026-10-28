"""Database connection + tiny migration runner."""
from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT / "migrations"

load_dotenv(ROOT / ".env")


def get_conn(url: str | None = None) -> psycopg.Connection:
    """Open a connection. Rows come back as dicts. Autocommit; use conn.transaction() for atomic work."""
    url = url or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and edit it.")
    return psycopg.connect(url, row_factory=dict_row, autocommit=True)


def migrate(conn) -> list[str]:
    """Apply every migrations/*.sql file that has not been applied yet. Returns applied names."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()}
    applied = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied


if __name__ == "__main__":  # python -m finance.db  -> create / upgrade tables
    with get_conn() as c:
        names = migrate(c)
    print("Applied:", ", ".join(names) if names else "nothing (already up to date)")
