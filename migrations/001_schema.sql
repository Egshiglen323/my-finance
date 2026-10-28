-- 001_schema.sql : core tables

CREATE TABLE banks (
    id    SERIAL PRIMARY KEY,
    code  TEXT UNIQUE NOT NULL,          -- 'KHAN', later 'GOLOMT', 'TDB', ...
    name  TEXT NOT NULL
);

CREATE TABLE accounts (
    id             SERIAL PRIMARY KEY,
    bank_id        INT REFERENCES banks(id),
    account_no     TEXT UNIQUE NOT NULL,
    iban           TEXT,
    currency       TEXT NOT NULL DEFAULT 'MNT',
    holder         TEXT,
    nickname       TEXT,
    is_own         BOOLEAN NOT NULL DEFAULT TRUE,   -- transfers to/from own accounts are not income/expense
    has_statements BOOLEAN NOT NULL DEFAULT FALSE   -- TRUE when we import statements for it
);

CREATE TABLE imports (
    id            SERIAL PRIMARY KEY,
    account_id    INT NOT NULL REFERENCES accounts(id),
    file_name     TEXT NOT NULL,
    file_sha256   TEXT UNIQUE NOT NULL,
    period_from   DATE,
    period_to     DATE,
    rows_read     INT NOT NULL DEFAULT 0,
    rows_inserted INT NOT NULL DEFAULT 0,
    imported_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE categories (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('income', 'expense', 'transfer')),
    sort_order INT  NOT NULL DEFAULT 100,
    UNIQUE (kind, name)
);

CREATE TABLE merchants (
    id                  SERIAL PRIMARY KEY,
    match_key           TEXT UNIQUE NOT NULL,   -- 'DESC:EMART HUNNU' or 'ACC:5954669628'
    display_name        TEXT NOT NULL,
    default_category_id INT REFERENCES categories(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE rules (
    id          SERIAL PRIMARY KEY,
    priority    INT  NOT NULL DEFAULT 100,   -- lower number = checked first
    field       TEXT NOT NULL CHECK (field IN ('description', 'counterparty', 'amount')),
    op          TEXT NOT NULL CHECK (op IN ('contains', 'equals', 'regex', 'between')),
    value       TEXT NOT NULL,               -- for 'between': "min,max" (absolute amount)
    direction   TEXT CHECK (direction IN ('credit', 'debit')),   -- NULL = both
    category_id INT  NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    note        TEXT
);

CREATE TABLE transactions (
    id                   BIGSERIAL PRIMARY KEY,
    account_id           INT NOT NULL REFERENCES accounts(id),
    import_id            INT REFERENCES imports(id) ON DELETE SET NULL,
    txn_time             TIMESTAMP NOT NULL,
    branch               TEXT,
    amount               NUMERIC(18,2) NOT NULL,     -- + credit (money in) / - debit (money out)
    balance_before       NUMERIC(18,2),
    balance_after        NUMERIC(18,2),
    description          TEXT,
    counterparty_account TEXT,
    merchant_id          INT REFERENCES merchants(id) ON DELETE SET NULL,
    category_id          INT REFERENCES categories(id) ON DELETE SET NULL,
    class_source         TEXT CHECK (class_source IN ('merchant', 'rule', 'own_account', 'manual')),
    note                 TEXT,
    dedupe_hash          TEXT UNIQUE NOT NULL
);

CREATE INDEX ix_txn_time     ON transactions (txn_time);
CREATE INDEX ix_txn_category ON transactions (category_id);
CREATE INDEX ix_txn_merchant ON transactions (merchant_id);
