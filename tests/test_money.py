from decimal import Decimal

import pytest

from bp.money import is_amount, is_year, parse_amount


@pytest.mark.parametrize("text, expected", [
    ("1.234,56", Decimal("1234.56")),
    ("45.270,00", Decimal("45270.00")),
    ("-5.826,00", Decimal("-5826.00")),
    ("126,37385", Decimal("126.37385")),
    ("0,267", Decimal("0.267")),
    ("3207.4", Decimal("3207.4")),
])
def test_parse_amount(text, expected):
    assert is_amount(text)
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["2025", "4263", "16/09/2024", "IT60X054", "c/DIP", "1.234"])
def test_not_amount(text):
    assert not is_amount(text)


def test_year():
    assert is_year("2025")
    assert not is_year("4263")
