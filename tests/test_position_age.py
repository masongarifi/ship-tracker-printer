from fleet_receipt.formatting import format_age


def test_position_age_wording():
    assert format_age(30) == "<1 minute"
    assert format_age(60) == "1 minute"
    assert format_age(8 * 60) == "8 minutes"
    assert format_age(3600) == "1 hour"
    assert format_age(11 * 3600) == "11 hours"
