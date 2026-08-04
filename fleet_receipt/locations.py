import math
from typing import Optional, Tuple

from .models import Location, Position
from .unlocode import nearest_unlocode

STATIONARY_PLACE_LIMIT_KM = 25 * 1.852


# Ordered from the most specific marine feature to broad ocean coverage.
# Each entry is (name, south, west, north, east, timezone).
MARINE_AREAS = (
    ("Strait of Messina", 37.75, 15.25, 38.55, 15.80, "Europe/Rome"),
    ("Strait of Gibraltar", 35.75, -6.20, 36.30, -5.20, "Europe/Madrid"),
    ("English Channel", 48.40, -6.20, 51.30, 2.00, "Europe/London"),
    ("Puget Sound", 47.00, -123.30, 49.10, -122.10, "America/Los_Angeles"),
    ("Inside Passage", 48.50, -135.50, 58.80, -126.00, "America/Vancouver"),
    ("The Minch", 56.90, -7.10, 58.80, -5.00, "Europe/London"),
    ("Tasman Sea", -48.00, 145.00, -28.00, 174.00, "Australia/Sydney"),
    ("Caribbean Sea", 9.00, -89.00, 23.00, -59.00, "America/Puerto_Rico"),
    ("Mediterranean Sea", 30.00, -6.00, 46.00, 36.00, "Europe/Rome"),
    ("North Sea", 51.00, -4.00, 62.00, 9.50, "Europe/London"),
    ("North Atlantic Ocean", 0.00, -80.00, 70.00, -6.20, "Atlantic/Azores"),
    ("South Atlantic Ocean", -60.00, -70.00, 0.00, 20.00, "Atlantic/South_Georgia"),
    ("North Pacific Ocean", 0.00, 100.00, 66.00, -100.00, None),
    ("South Pacific Ocean", -60.00, 140.00, 0.00, -70.00, None),
    ("Indian Ocean", -60.00, 20.00, 30.00, 120.00, None),
    ("Southern Ocean", -90.00, -180.00, -60.00, 180.00, None),
    ("Arctic Ocean", 66.00, -180.00, 90.00, 180.00, None),
)

# Curated operational port/city boundaries used before broad marine areas.
# (display name, locality, south, west, north, east, timezone)
PORT_AREAS = (
    (
        "Port of Amsterdam",
        "Amsterdam, Netherlands",
        52.365,
        4.690,
        52.430,
        4.970,
        "Europe/Amsterdam",
    ),
    (
        "Port of Rotterdam",
        "Rotterdam, Netherlands",
        51.880,
        3.930,
        52.020,
        4.570,
        "Europe/Amsterdam",
    ),
    (
        "Port of Seattle",
        "Seattle, Washington",
        47.570,
        -122.380,
        47.660,
        -122.310,
        "America/Los_Angeles",
    ),
)

# (locality, south, west, north, east, timezone)
CITY_AREAS = (
    ("Amsterdam, Netherlands", 52.280, 4.700, 52.430, 5.020, "Europe/Amsterdam"),
    ("Rotterdam, Netherlands", 51.850, 4.300, 52.050, 4.650, "Europe/Amsterdam"),
    ("Seattle, Washington", 47.480, -122.460, 47.740, -122.220, "America/Los_Angeles"),
)

# (place, country/region, latitude, longitude, timezone)
MAJOR_PORTS = (
    ("Juneau", "Alaska", 58.3019, -134.4197, "America/Juneau"),
    ("Ketchikan", "Alaska", 55.3422, -131.6461, "America/Sitka"),
    ("Vancouver", "British Columbia", 49.2897, -123.1119, "America/Vancouver"),
    ("Seattle", "Washington", 47.6062, -122.3321, "America/Los_Angeles"),
    ("Cartagena", "Colombia", 10.3910, -75.4794, "America/Bogota"),
    ("Reykjavik", "Iceland", 64.1466, -21.9426, "Atlantic/Reykjavik"),
    ("Stavanger", "Norway", 58.9700, 5.7331, "Europe/Oslo"),
    ("Barcelona", "Spain", 41.3525, 2.1589, "Europe/Madrid"),
    ("Piraeus", "Greece", 37.9420, 23.6465, "Europe/Athens"),
    ("Dover", "England", 51.1279, 1.3134, "Europe/London"),
    ("Cherbourg", "France", 49.6337, -1.6221, "Europe/Paris"),
    ("Amsterdam", "Netherlands", 52.3783, 4.9167, "Europe/Amsterdam"),
    ("IJmuiden", "Netherlands", 52.4586, 4.6178, "Europe/Amsterdam"),
    ("Rotterdam", "Netherlands", 51.9244, 4.4777, "Europe/Amsterdam"),
    ("Sydney", "Australia", -33.8568, 151.2153, "Australia/Sydney"),
    ("Auckland", "New Zealand", -36.8406, 174.7400, "Pacific/Auckland"),
    ("Yokohama", "Japan", 35.4437, 139.6380, "Asia/Tokyo"),
    ("Singapore", "Singapore", 1.2644, 103.8200, "Asia/Singapore"),
)


def get_friendly_location(latitude: float, longitude: float) -> str:
    """Return an offline, human-readable marine location for a coordinate."""
    _validate_coordinates(latitude, longitude)

    city_area = _containing_city(latitude, longitude)
    if city_area is not None:
        return city_area[0]

    port_area = _containing_port(latitude, longitude)
    if port_area is not None:
        return port_area[0]

    port = _nearest_port(latitude, longitude)
    if port is not None and port[0] <= 9.26:  # 5 nautical miles
        _, name, region, _, _, _ = port
        return f"Near {name}, {region}"

    area = _marine_area(latitude, longitude)
    if area is not None and _area_priority(area[0]) <= 3:
        return area[0]

    if area is not None:
        return area[0]

    # Full-world broad fallback; this should only be reached in marginal polygons.
    return "Pacific Ocean" if abs(longitude) >= 100 else "Atlantic Ocean"


def get_nearest_landmark(latitude: float, longitude: float) -> Optional[str]:
    """Return distance and bearing from a useful nearby major port."""
    _validate_coordinates(latitude, longitude)
    if _containing_city(latitude, longitude) is not None:
        return None
    port_area = _containing_port(latitude, longitude)
    if port_area is not None:
        return port_area[1]
    port = _nearest_port(latitude, longitude)
    if port is None or port[0] <= 9.26 or port[0] > 277.8:
        return None
    distance_km, name, region, port_lat, port_lon, _ = port
    nautical_miles = round(distance_km / 1.852)
    direction = _compass_direction(
        initial_bearing(port_lat, port_lon, latitude, longitude)
    )
    return f"{nautical_miles} nm {direction} of {name}, {region}"


def resolve_location(position: Position) -> Location:
    """Resolve display name plus the best available timezone for a position."""
    name = get_friendly_location(position.latitude, position.longitude)
    timezone_name: Optional[str] = None
    kind = "marine"
    distance_km: Optional[float] = None

    city_area = _containing_city(position.latitude, position.longitude)
    port_area = _containing_port(position.latitude, position.longitude)
    port = _nearest_port(position.latitude, position.longitude)
    stationary_port_limit = _stationary_port_limit(position.navigational_status)
    place_limit = stationary_port_limit or 9.26
    indexed_place = nearest_unlocode(
        position.latitude, position.longitude, place_limit
    )
    if city_area is not None:
        timezone_name = city_area[5]
        kind = "city"
    elif port_area is not None:
        name = port_area[1]
        timezone_name = port_area[6]
        kind = "port"
    elif indexed_place is not None:
        distance, name, kind = indexed_place
        distance_km = distance
        if _is_anchored(position.navigational_status) and distance > 9.26:
            name = f"Anchored off {name}"
    elif port is not None and port[0] <= 9.26:
        timezone_name = port[5]
        kind = "port"
        distance_km = port[0]
    elif (
        port is not None
        and stationary_port_limit is not None
        and port[0] <= stationary_port_limit
    ):
        _, port_name, region, _, _, timezone_name = port
        name = f"{port_name}, {region}"
        kind = "port"
        distance_km = port[0]
    if timezone_name is None:
        area = _marine_area(position.latitude, position.longitude)
        timezone_name = area[5] if area is not None else None
    if timezone_name is None:
        timezone_name = position.broad_timezone
    return Location(name, timezone_name, kind, distance_km)


def _stationary_port_limit(status: str) -> Optional[float]:
    """Return a conservative port/anchorage search radius in kilometres."""
    normalized = " ".join(status.strip().casefold().split())
    if normalized in {"moored", "anchored", "at anchor"}:
        return STATIONARY_PLACE_LIMIT_KM
    return None


def _is_anchored(status: str) -> bool:
    return " ".join(status.strip().casefold().split()) in {"anchored", "at anchor"}


def format_coordinates(latitude: float, longitude: float) -> str:
    """Format coordinates in compact bridge-report degrees and minutes."""
    _validate_coordinates(latitude, longitude)
    return f"{_coordinate(latitude, True)} {_coordinate(longitude, False)}"


def split_coordinates(latitude: float, longitude: float) -> Tuple[str, str]:
    _validate_coordinates(latitude, longitude)
    return _coordinate(latitude, True), _coordinate(longitude, False)


def _coordinate(value: float, latitude: bool) -> str:
    direction = ("N" if value >= 0 else "S") if latitude else ("E" if value >= 0 else "W")
    absolute = abs(value)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60
    width = 2 if latitude else 3
    return f"{degrees:0{width}d}°{minutes:04.1f}'{direction}"


def _marine_area(latitude: float, longitude: float):
    for area in MARINE_AREAS:
        _, south, west, north, east, _ = area
        longitude_matches = west <= longitude <= east if west <= east else (
            longitude >= west or longitude <= east
        )
        if south <= latitude <= north and longitude_matches:
            return area
    return None


def _containing_port(latitude: float, longitude: float):
    for area in PORT_AREAS:
        _, _, south, west, north, east, _ = area
        if south <= latitude <= north and west <= longitude <= east:
            return area
    return None


def _containing_city(latitude: float, longitude: float):
    for area in CITY_AREAS:
        _, south, west, north, east, _ = area
        if south <= latitude <= north and west <= longitude <= east:
            return area
    return None


def _area_priority(name: str) -> int:
    if "Strait" in name or "Channel" in name or name in {"The Minch", "Inside Passage"}:
        return 1
    if "Sea" in name:
        return 2
    if any(word in name for word in ("Gulf", "Bay", "Sound")):
        return 3
    return 4


def _nearest_port(latitude: float, longitude: float):
    nearest = None
    for name, region, port_lat, port_lon, timezone_name in MAJOR_PORTS:
        distance = haversine_km(latitude, longitude, port_lat, port_lon)
        candidate = (distance, name, region, port_lat, port_lon, timezone_name)
        if nearest is None or distance < nearest[0]:
            nearest = candidate
    return nearest


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Latitude or longitude is outside the valid range")


def _compass_direction(bearing: float) -> str:
    directions = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    return directions[int((bearing + 22.5) // 45) % 8]


def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    delta_lon = math.radians(lon2 - lon1)
    y = math.sin(delta_lon) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))
