import json
from pathlib import Path
from typing import Any, Dict

from .models import FleetData, Vessel

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


def load_fleet(path: Path = PROJECT_ROOT / "config" / "fleet.yaml") -> FleetData:
    data = _load_yaml_compatible(path)
    order = []
    vessels = []
    seen = set()
    for line in data.get("cruise_lines", []):
        line_name = str(line["name"]).strip()
        order.append(line_name)
        for item in line.get("vessels", []):
            name = str(item["name"]).strip()
            key = name.casefold()
            if key in seen:
                raise ConfigurationError(f"Duplicate vessel name: {name}")
            seen.add(key)
            vessels.append(
                Vessel(
                    cruise_line=line_name,
                    name=name,
                    imo=_identifier(item.get("imo")),
                    mmsi=_identifier(item.get("mmsi")),
                    active=bool(item.get("active", True)),
                    notes=item.get("notes"),
                )
            )
    return FleetData(tuple(order), tuple(vessels))


def _identifier(value: Any):
    if value is None or value == "":
        return None
    return str(value)


def load_settings(path: Path = PROJECT_ROOT / "config" / "settings.yaml") -> Dict[str, Any]:
    return _load_yaml_compatible(path)

