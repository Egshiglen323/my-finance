"""One-time setup: creates the 'finance' PostgreSQL user + database, writes .env, creates tables.
Run by setup.bat / setup.sh. Safe to run again."""
from __future__ import annotations

import getpass
import secrets
import sys
from pathlib import Path
from urllib.parse import quote

import psycopg

ROOT = Path(__file__).resolve().parent
ENV = ROOT / ".env"


def create_database() -> None:
    print("\n=== PostgreSQL setup ===")
    host = input("PostgreSQL host [localhost]: ").strip() or "localhost"
    port = input("PostgreSQL port [5432]: ").strip() or "5432"
    admin_pw = getpass.getpass("Password of the 'postgres' user (the one you set when installing PostgreSQL): ")
    try:
        admin = psycopg.connect(f"postgresql://postgres:{quote(admin_pw, safe='')}@{host}:{port}/postgres",
                                autocommit=True)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"\nCould not connect to PostgreSQL: {e}\n"
                 "Check that PostgreSQL is running and the password is correct, then run setup again.")

    app_pw = secrets.token_urlsafe(18)   # only letters, digits, - and _  -> safe inside SQL quotes
    if admin.execute("SELECT 1 FROM pg_roles WHERE rolname = 'finance'").fetchone():
        admin.execute(f"ALTER ROLE finance WITH LOGIN PASSWORD '{app_pw}'")
    else:
        admin.execute(f"CREATE ROLE finance LOGIN PASSWORD '{app_pw}'")
    if not admin.execute("SELECT 1 FROM pg_database WHERE datname = 'finance'").fetchone():
        admin.execute("CREATE DATABASE finance OWNER finance")
        print("Database 'finance' created.")
    else:
        print("Database 'finance' already exists - keeping your data.")
    admin.close()

    ENV.write_text(f"DATABASE_URL=postgresql://finance:{app_pw}@{host}:{port}/finance\n", encoding="utf-8")
    print(f"Saved connection settings to {ENV.name}")


def main() -> None:
    if ENV.exists():
        print(f"{ENV.name} already exists - skipping user/database creation "
              f"(delete {ENV.name} and run setup again to redo it).")
    else:
        create_database()

    from finance.db import get_conn, migrate   # imported after .env exists
    with get_conn() as conn:
        applied = migrate(conn)
    print("Tables:", "created " + ", ".join(applied) if applied else "already up to date")
    print("\nSetup finished. Start the app with run.bat (Windows) or ./run.sh (Mac/Linux).")


if __name__ == "__main__":
    main()
