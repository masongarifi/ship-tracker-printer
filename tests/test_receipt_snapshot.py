from fleet_receipt.formatting import format_receipt


def test_bridge_watch_block_layout(fleet, positions, report_time):
    receipt = format_receipt(fleet, positions, report_time)
    block = receipt.split("NIEUW STATENDAM", 1)[1].split("NOORDAM", 1)[0]

    assert "English Channel" in block
    assert "70 nm SW of Dover, England" in block
    assert "50°12.0'N 000°12.0'E" in block
    assert "\nUNDERWAY\n16.4 kt\n" in block
    assert "Course 065°" in block
    assert "\nDestination\nROTTERDAM\n" in block
    assert "\nUTC 23:05\nLocal 00:05 (+8 Seattle)\n" in block
    assert "\nUpdated\n13 minutes ago\n" in block
