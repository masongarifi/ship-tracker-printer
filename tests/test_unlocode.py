import zipfile
from pathlib import Path

from fleet_receipt.formatting_helpers import format_destination
from fleet_receipt.unlocode import (
    CSV_PARTS,
    SUBDIVISIONS_CSV,
    build_database_from_archive,
    database_status,
    lookup_unlocode,
    nearest_unlocode,
)


def make_archive(path: Path) -> None:
    parts = {
        CSV_PARTS[0]: (
            ",GB,,.UNITED KINGDOM,,,,,,,,\n"
            ",GB,DVR,Dover,Dover,,1-------,AA,2501,,5108N 00119E,\n"
            ",JP,,.JAPAN,,,,,,,,\n"
            ",JP,TYO,Tokyo,Tokyo,13,1--4----,AA,2501,,3541N 13941E,\n"
        ),
        CSV_PARTS[1]: (
            ",US,,.UNITED STATES,,,,,,,,\n"
            ",US,SEA,Seattle,Seattle,WA,1--4----,AA,2501,,4736N 12220W,\n"
        ),
        CSV_PARTS[2]: (
            ",CA,,.CANADA,,,,,,,,\n"
            ",CA,VAN,Vancouver,Vancouver,BC,1--4----,AA,2501,,4915N 12307W,\n"
        ),
        SUBDIVISIONS_CSV: (
            "JP,13,Tokyo,Prefecture\n"
            "US,WA,Washington,State\n"
            "CA,BC,British Columbia,Province\n"
        ),
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for member, content in parts.items():
            archive.writestr(member, content)


def test_complete_index_builder_imports_all_archive_parts(tmp_path):
    archive = tmp_path / "unlocode.zip"
    database = tmp_path / "unlocode.sqlite3"
    make_archive(archive)

    assert build_database_from_archive(archive, database) == 4
    assert lookup_unlocode("GB DVR", database) == "Dover, United Kingdom"
    assert lookup_unlocode("JP TYO", database) == "Tokyo, Japan"
    assert lookup_unlocode("US SEA", database) == "Seattle, Washington"
    assert lookup_unlocode("CA VAN", database) == "Vancouver, British Columbia"


def test_database_status_records_release_and_count(tmp_path):
    archive = tmp_path / "unlocode.zip"
    database = tmp_path / "unlocode.sqlite3"
    make_archive(archive)
    build_database_from_archive(archive, database)

    status = database_status(database)

    assert status["available"] is True
    assert status["release"] == "2025-1"
    assert status["location_count"] == 4


def test_nearest_populated_place_uses_coordinates_and_human_label(tmp_path):
    archive = tmp_path / "unlocode.zip"
    database = tmp_path / "unlocode.sqlite3"
    make_archive(archive)
    build_database_from_archive(archive, database)

    place = nearest_unlocode(47.61, -122.34, 25 * 1.852, database)

    assert place is not None
    distance, label, kind = place
    assert distance < 2
    assert label == "Seattle, Washington"
    assert kind == "city"


def test_destination_formatter_uses_local_complete_index(tmp_path, monkeypatch):
    data_directory = tmp_path / "app-data"
    archive = tmp_path / "unlocode.zip"
    database = data_directory / "unlocode.sqlite3"
    data_directory.mkdir()
    make_archive(archive)
    build_database_from_archive(archive, database)
    monkeypatch.setenv("SHIP_TRACKER_DATA_DIR", str(data_directory))

    # JP TYO is deliberately absent from the built-in emergency aliases.
    assert format_destination("JP TYO") == "Tokyo, Japan"


def test_unknown_code_still_falls_back_after_database_lookup(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIP_TRACKER_DATA_DIR", str(tmp_path))
    assert format_destination("XZ ZZZ") == "Xz Zzz"
