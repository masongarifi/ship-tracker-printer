import pytest

from fleet_receipt.ais_status import (
    AIS_NAVIGATIONAL_STATUSES,
    is_underway_status,
    navigational_status,
)


@pytest.mark.parametrize("code, label", sorted(AIS_NAVIGATIONAL_STATUSES.items()))
def test_all_ais_navigational_status_codes(code, label):
    assert navigational_status(code) == label
    assert navigational_status(str(code)) == label


def test_readable_status_is_preserved():
    assert navigational_status("  Moored  ") == "Moored"


@pytest.mark.parametrize("value", [-1, 16, "99", "", None, True])
def test_invalid_status_is_safe(value):
    assert navigational_status(value) == "Navigational status unavailable"


def test_underway_normalization_handles_ais_codes_and_readable_variants():
    assert is_underway_status(0)
    assert is_underway_status("Under way")
    assert is_underway_status("Underway")
    assert is_underway_status("Under way under sailing only")
    assert not is_underway_status("Moored")
    assert not is_underway_status("At anchor")
