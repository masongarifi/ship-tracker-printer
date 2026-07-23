import csv
import io
import os
import sqlite3
import tempfile
import urllib.request
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Optional

from .cache import application_data_directory

UNLOCODE_RELEASE = "2025-1"
UNLOCODE_DOWNLOAD_URL = (
    "https://opensource.unicc.org/un/unece/uncefact/vocab-locode/"
    "-/jobs/artifacts/2025-1/download?job=package-release"
)
UNLOCODE_DATABASE_NAME = "unlocode.sqlite3"
CSV_PARTS = (
    "release/csv/UNLOCODE CodeListPart1.csv",
    "release/csv/UNLOCODE CodeListPart2.csv",
    "release/csv/UNLOCODE CodeListPart3.csv",
)
SUBDIVISIONS_CSV = "release/csv/SubdivisionCodes.csv"


class UNLocodeSyncError(RuntimeError):
    pass


def default_unlocode_path() -> Path:
    return application_data_directory() / UNLOCODE_DATABASE_NAME


def unlocode_available(path: Optional[Path] = None) -> bool:
    database = Path(path) if path is not None else default_unlocode_path()
    if not database.exists():
        return False
    try:
        with closing(sqlite3.connect(database)) as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'release'"
            ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def lookup_unlocode(code: str, path: Optional[Path] = None) -> Optional[str]:
    normalized = _normalize_code(code)
    if normalized is None:
        return None
    database = Path(path) if path is not None else default_unlocode_path()
    if not database.exists():
        return None
    try:
        with closing(sqlite3.connect(database)) as connection:
            row = connection.execute(
                """
                SELECT
                    locations.name,
                    locations.country_code,
                    countries.name,
                    subdivisions.name
                FROM locations
                LEFT JOIN countries
                    ON countries.code = locations.country_code
                LEFT JOIN subdivisions
                    ON subdivisions.country_code = locations.country_code
                    AND subdivisions.code = locations.subdivision_code
                WHERE locations.locode = ?
                """,
                (normalized,),
            ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    location, country_code, country, subdivision = row
    qualifiers = []
    if country_code in {"US", "CA"} and subdivision:
        qualifiers.append(subdivision)
    elif country and country.casefold() != location.casefold():
        qualifiers.append(country)
    return ", ".join((location, *qualifiers))


def sync_unlocode(
    path: Optional[Path] = None,
    download_url: str = UNLOCODE_DOWNLOAD_URL,
) -> int:
    database = Path(path) if path is not None else default_unlocode_path()
    database.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        download_url,
        headers={"User-Agent": "ship-tracker-printer/0.1 UNLOCODE sync"},
    )
    temporary_archive = None
    try:
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                with tempfile.NamedTemporaryFile(
                    prefix="unlocode-",
                    suffix=".zip",
                    dir=database.parent,
                    delete=False,
                ) as output:
                    temporary_archive = Path(output.name)
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
            return build_database_from_archive(temporary_archive, database)
        except (OSError, ValueError, csv.Error, sqlite3.Error, zipfile.BadZipFile) as exc:
            raise UNLocodeSyncError(f"official dataset sync failed: {exc}") from exc
    finally:
        if temporary_archive is not None:
            temporary_archive.unlink(missing_ok=True)


def build_database_from_archive(archive_path: Path, database_path: Path) -> int:
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_database = database_path.with_suffix(".building.sqlite3")
    temporary_database.unlink(missing_ok=True)

    count = 0
    try:
        with closing(sqlite3.connect(temporary_database)) as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = FULL;
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE countries (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL
                );
                CREATE TABLE subdivisions (
                    country_code TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    PRIMARY KEY (country_code, code)
                );
                CREATE TABLE locations (
                    locode TEXT PRIMARY KEY,
                    country_code TEXT NOT NULL,
                    location_code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    name_ascii TEXT,
                    subdivision_code TEXT,
                    function TEXT,
                    status TEXT
                );
                CREATE INDEX locations_country_code
                    ON locations (country_code, location_code);
                """
            )
            with zipfile.ZipFile(archive_path) as archive:
                _import_subdivisions(connection, archive)
                for member in CSV_PARTS:
                    count += _import_locations(connection, archive, member)
            connection.executemany(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                (("release", UNLOCODE_RELEASE), ("location_count", str(count))),
            )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise sqlite3.DatabaseError(f"UN/LOCODE index integrity check: {integrity}")
            connection.commit()
        os.replace(temporary_database, database_path)
        if os.name != "nt":
            database_path.chmod(0o600)
        return count
    except Exception:
        temporary_database.unlink(missing_ok=True)
        raise


def database_status(path: Optional[Path] = None) -> dict:
    database = Path(path) if path is not None else default_unlocode_path()
    result = {"path": str(database), "available": False}
    if not database.exists():
        return result
    try:
        with closing(sqlite3.connect(database)) as connection:
            values = dict(connection.execute("SELECT key, value FROM metadata"))
        result.update(
            {
                "available": True,
                "release": values.get("release"),
                "location_count": int(values.get("location_count", 0)),
            }
        )
    except (sqlite3.Error, ValueError):
        pass
    return result


def _import_subdivisions(
    connection: sqlite3.Connection, archive: zipfile.ZipFile
) -> None:
    rows = _csv_rows(archive, SUBDIVISIONS_CSV)
    connection.executemany(
        """
        INSERT OR REPLACE INTO subdivisions (country_code, code, name)
        VALUES (?, ?, ?)
        """,
        (
            (row[0].strip().upper(), row[1].strip().upper(), row[2].strip())
            for row in rows
            if len(row) >= 3 and row[0].strip() and row[1].strip() and row[2].strip()
        ),
    )


def _import_locations(
    connection: sqlite3.Connection, archive: zipfile.ZipFile, member: str
) -> int:
    locations = []
    countries = []
    for row in _csv_rows(archive, member):
        if len(row) < 8:
            continue
        country_code = row[1].strip().upper()
        location_code = row[2].strip().upper()
        name = row[3].strip()
        if country_code and not location_code and name.startswith("."):
            countries.append((country_code, _title_country(name.lstrip("."))))
            continue
        if not (len(country_code) == 2 and len(location_code) == 3 and name):
            continue
        locations.append(
            (
                country_code + location_code,
                country_code,
                location_code,
                name,
                row[4].strip() or None,
                row[5].strip().upper() or None,
                row[6].strip() or None,
                row[7].strip() or None,
            )
        )
    connection.executemany(
        "INSERT OR REPLACE INTO countries (code, name) VALUES (?, ?)", countries
    )
    connection.executemany(
        """
        INSERT OR REPLACE INTO locations (
            locode, country_code, location_code, name, name_ascii,
            subdivision_code, function, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        locations,
    )
    return len(locations)


def _csv_rows(archive: zipfile.ZipFile, member: str):
    with archive.open(member) as binary:
        with io.TextIOWrapper(
            binary, encoding="utf-8-sig", errors="replace", newline=""
        ) as text:
            yield from csv.reader(text)


def _normalize_code(value: str) -> Optional[str]:
    compact = "".join(character for character in value.upper() if character.isalnum())
    return compact if len(compact) == 5 else None


def _title_country(value: str) -> str:
    return value.title().replace(" Of ", " of ").replace(" And ", " and ")
