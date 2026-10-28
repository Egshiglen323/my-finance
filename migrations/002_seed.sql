-- 002_seed.sql : banks, default categories, starter rules

INSERT INTO banks (code, name) VALUES ('KHAN', 'Khan Bank');

INSERT INTO categories (kind, name, sort_order) VALUES
    ('income',   'Self-earned (salary, freelance)', 10),
    ('income',   'Gift / Donation received',        20),
    ('income',   'Refund',                          30),
    ('income',   'Interest',                        40),
    ('income',   'Other income',                    99),

    ('expense',  'Personal care',                   10),
    ('expense',  'Groceries',                       20),
    ('expense',  'Healthcare',                      30),
    ('expense',  'Savings',                         40),
    ('expense',  'Food & cafés',                    50),
    ('expense',  'Transport (taxi, fuel, bus)',     60),
    ('expense',  'Utilities (power, heating, internet)', 70),
    ('expense',  'Mobile & subscriptions',          80),
    ('expense',  'Housing / Rent',                  90),
    ('expense',  'Education',                      100),
    ('expense',  'Clothing & shopping',            110),
    ('expense',  'Entertainment',                  120),
    ('expense',  'Gifts / Donations given',        130),
    ('expense',  'Loan repayment',                 140),
    ('expense',  'Bank fees',                      150),
    ('expense',  'Other expense',                  199),

    ('transfer', 'Own-account transfer',            10),
    ('transfer', 'Cash withdrawal',                 20);

-- Starter rules (edit them on the Rules page)
INSERT INTO rules (priority, field, op, value, direction, category_id, note)
SELECT 10, 'description', 'contains', 'ХУРААМЖ', 'debit', id, 'Khan Bank account/service fee'
FROM categories WHERE kind = 'expense' AND name = 'Bank fees';

INSERT INTO rules (priority, field, op, value, direction, category_id, note)
SELECT 50, 'description', 'regex', '\bATM\b', 'debit', id, 'ATM cash withdrawal'
FROM categories WHERE kind = 'transfer' AND name = 'Cash withdrawal';
