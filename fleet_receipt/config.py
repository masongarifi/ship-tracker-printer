import json
from pathlib import Path
from typing import Any, Dict

from .models import FleetData, Vessel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_LINE_ALIASES = {
    "hal": {"Holland America Line"},
    "seabourn": {"Seabourn"},
}


class ConfigurationError(ValueError):
    pass


def _load_yaml_compatible(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise ConfigurationError(
                f"{path} uses YAML syntax; install PyYAML or use JSON-compatible YAML"
            ) from exc
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ConfigurationError(f"{path} must contain a mapping")
        return data


def load_fleet(
    path: Path = PROJECT_ROOT / "config" / "fleet.yaml",
    profile: str = "main",
) -> FleetData:
    data = _load_yaml_compatible(path)
    selected_profile = profile.strip().casefold()
    if not selected_profile:
        raise ConfigurationError("Fleet profile cannot be empty")
    order = []
    vessels = []
    seen = set()
    configured_profiles = set()
    for line in data.get("cruise_lines", []):
        line_name = str(line["name"]).strip()
        line_profile = str(line.get("profile") or "main").strip().casefold()
        configured_profiles.add(line_profile)
        alias_lines = PROFILE_LINE_ALIASES.get(selected_profile)
        if (
            selected_profile != "all"
            and line_profile != selected_profile
            and (alias_lines is None or line_name not in alias_lines)
        ):
            continue
        order.append(line_name)
        line_mmsis = set()
        line_imos = set()
        for item in line.get("vessels", []):
            if not isinstance(item, dict):
                raise ConfigurationError(f"{line_name} contains an invalid vessel entry")
            name = str(item.get("name") or "").strip()
            if not name:
                raise ConfigurationError(f"{line_name} contains a vessel with no name")
            key = name.casefold()
            if key in seen:
                raise ConfigurationError(f"Duplicate vessel name: {name}")
            seen.add(key)
            imo = _validated_identifier(item.get("imo"), "IMO", name)
            mmsi = _validated_identifier(item.get("mmsi"), "MMSI", name)
            if mmsi in line_mmsis:
                raise ConfigurationError(f"Duplicate MMSI in {line_name}: {mmsi}")
            if imo in line_imos:
                raise ConfigurationError(f"Duplicate IMO in {line_name}: {imo}")
            if mmsi:
                line_mmsis.add(mmsi)
            if imo:
                line_imos.add(imo)
            vessels.append(
                Vessel(
                    cruise_line=line_name,
                    name=name,
                    imo=imo,
                    mmsi=mmsi,
                    active=bool(item.get("active", True)),
                    notes=item.get("notes"),
                )
            )
    if (
        selected_profile != "all"
        and selected_profile not in configured_profiles
        and selected_profile not in PROFILE_LINE_ALIASES
    ):
        raise ConfigurationError(f"Unknown fleet profile: {profile}")
    return FleetData(tuple(order), tuple(vessels))


def _validated_identifier(value: Any, kind: str, vessel_name: str):
    if value is None or value == "":
        return None
    identifier = str(value)
    expected_length = 9 if kind == "MMSI" else 7
    if not identifier.isdigit() or len(identifier) != expected_length:
        raise ConfigurationError(f"Malformed {kind} for {vessel_name}: {identifier}")
    if kind == "IMO":
        check_digit = sum(int(digit) * weight for digit, weight in zip(identifier, range(7, 1, -1)))
        if check_digit % 10 != int(identifier[-1]):
            raise ConfigurationError(f"Malformed IMO for {vessel_name}: {identifier}")
    return identifier


def load_settings(path: Path = PROJECT_ROOT / "config" / "settings.yaml") -> Dict[str, Any]:
    return _load_yaml_compatible(path)
