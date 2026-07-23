from fleet_receipt.formatting import sorted_active_vessels


def test_group_and_alphabetical_sorting(fleet):
    vessels = sorted_active_vessels(fleet)
    lines = [v.cruise_line for v in vessels]
    first_seabourn = lines.index("Seabourn")
    assert all(line == "Holland America Line" for line in lines[:first_seabourn])
    assert all(line == "Seabourn" for line in lines[first_seabourn:])
    for line in fleet.cruise_line_order:
        names = [v.name for v in vessels if v.cruise_line == line]
        assert names == sorted(names, key=str.casefold)


def test_all_sixteen_active_vessels_present_once(fleet):
    vessels = sorted_active_vessels(fleet)
    assert len(vessels) == 16
    assert len({v.name.casefold() for v in vessels}) == 16
    assert all(v.imo and v.imo.isdigit() for v in vessels)
    assert all(v.mmsi and v.mmsi.isdigit() for v in vessels)
