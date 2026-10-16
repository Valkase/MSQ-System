"""Unit tests for logic.transactions.calculate_split (task plan 2.2 / Phase 6)."""

from decimal import Decimal

import pytest

from logic.errors import ValidationError
from logic.transactions import calculate_split

D = Decimal


@pytest.mark.parametrize(
    "total,pct,doctor,center",
    [
        ("500.00", "60.00", "300.00", "200.00"),
        ("750.00", "50.00", "375.00", "375.00"),
        ("100.00", "0.00", "0.00", "100.00"),        # 0%: all to the center
        ("100.00", "100.00", "100.00", "0.00"),      # 100%: all to the doctor
        ("10.00", "33.33", "3.33", "6.67"),          # odd percentage, remainder to center
        ("99.99", "12.50", "12.50", "87.49"),        # 12.49875 rounds half-up to 12.50
        ("0.25", "50.00", "0.13", "0.12"),           # 0.125 -> 0.13 (half up), center absorbs
        ("0.01", "50.00", "0.01", "0.00"),           # smallest amount, 0.005 -> 0.01
        ("1000000.00", "37.50", "375000.00", "625000.00"),
    ],
)
def test_known_splits(total, pct, doctor, center):
    assert calculate_split(D(total), D(pct)) == (D(doctor), D(center))


def test_results_are_decimals_with_two_places():
    doctor, center = calculate_split(D("19.99"), D("45.55"))
    for value in (doctor, center):
        assert isinstance(value, Decimal)
        assert value == value.quantize(D("0.01"))


def test_split_always_adds_up_to_the_total_exactly():
    totals = ["0.01", "0.02", "0.03", "0.99", "1.00", "9.99", "10.05", "33.33", "123.45", "99999.99"]
    pcts = ["0.00", "0.01", "12.50", "33.33", "49.99", "50.00", "66.67", "99.99", "100.00"]
    for total in totals:
        for pct in pcts:
            doctor, center = calculate_split(D(total), D(pct))
            assert doctor + center == D(total), (total, pct)
            assert doctor >= 0 and center >= 0, (total, pct)


def test_integer_style_amounts_are_accepted():
    assert calculate_split(D("500"), D("60")) == (D("300.00"), D("200.00"))


@pytest.mark.parametrize("bad_total", ["0", "-5.00", "1.234", "NaN", "Infinity", "abc"])
def test_invalid_totals_are_rejected(bad_total):
    with pytest.raises(ValidationError):
        calculate_split(bad_total if bad_total == "abc" else D(bad_total), D("50.00"))


@pytest.mark.parametrize("bad_pct", ["-0.01", "100.01", "150", "33.333", "NaN"])
def test_invalid_percentages_are_rejected(bad_pct):
    with pytest.raises(ValidationError):
        calculate_split(D("100.00"), D(bad_pct))


def test_floats_are_rejected_outright():
    with pytest.raises(ValidationError):
        calculate_split(100.5, D("50.00"))
    with pytest.raises(ValidationError):
        calculate_split(D("100.00"), 50.0)