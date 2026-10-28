from decimal import Decimal

from finance.classifier import Rule, decide, rule_matches
from finance.merchants import merchant_key, normalize


def test_normalize_strips_noise():
    assert normalize("POS 2026.08.25 EMART HUNNU 1234 ULAANBAATAR MN") == "EMART HUNNU"
    assert normalize("CU 4111******1234 12:30:01") == "CU"


def test_merchant_key_uses_account_when_description_meaningless():
    assert merchant_key("q", "5954669628") == ("ACC:5954669628", "Account 5954669628")
    assert merchant_key("POS EMART HUNNU", None)[0] == "DESC:EMART HUNNU"
    assert merchant_key("ДАНС ХӨТӨЛСНИЙ ХУРААМЖ", None)[0] == "DESC:ДАНС ХӨТӨЛСНИЙ ХУРААМЖ"


def R(field, op, value, direction=None, cat=1, prio=100):
    return Rule(1, prio, field, op, value, direction, cat)


def test_rule_ops():
    assert rule_matches(R("description", "contains", "хураамж"), "ДАНС ХӨТӨЛСНИЙ ХУРААМЖ", None, Decimal(-93))
    assert not rule_matches(R("description", "contains", "ХУРААМЖ", "credit"), "ХУРААМЖ", None, Decimal(-93))
    assert rule_matches(R("counterparty", "equals", "5954669628"), "q", "5954669628", Decimal(-5))
    assert rule_matches(R("description", "regex", r"\bATM\b"), "ATM 123 KHAN", None, Decimal(-5))
    assert rule_matches(R("amount", "between", "1000,5000"), "", None, Decimal(-4999))
    assert not rule_matches(R("amount", "between", "1000,5000"), "", None, Decimal(-5001))
    assert rule_matches(R("amount", "between", "1000,"), "", None, Decimal(99999))


def test_decide_order():
    txn = {"merchant_id": 7, "description": "q", "counterparty_account": "111", "amount": Decimal(-10)}
    rules = [R("counterparty", "equals", "111", cat=2)]
    # merchant default beats rule
    assert decide(txn, rules, {7: 5}, {"111"}, 9) == (5, "merchant")
    # rule beats own account
    assert decide(txn, rules, {7: None}, {"111"}, 9) == (2, "rule")
    # own account last
    assert decide(txn, [], {7: None}, {"111"}, 9) == (9, "own_account")
    assert decide(txn, [], {}, set(), 9) == (None, None)
