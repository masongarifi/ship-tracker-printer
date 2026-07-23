import pytest

from fleet_receipt.ais_status import AIS_NAVIGATIONAL_STATUSES, navigational_status


@pytest.mark.parametrize("code, label", sorted(AIS_NAVIGATIONAL_STATUSES.items()))
def test_all_ais_navigational_status_codes(code, label):
    assert navigational_status(code) == label
    assert navigational_status(str(code)) == label


def test_readable_status_is_preserved():
    assert navigational_status("  Moored  ") == "Moored"


@pytest.mark.parametrize("value", [-1, 16, "99", "", None, True])
def test_invalid_status_is_safe(value):
    assert navigational_status(value) == "Navigational status unavailable"
