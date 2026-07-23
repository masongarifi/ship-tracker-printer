from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple


@dataclass(frozen=True)
class Vessel:
    cruise_line: str
    name: str
    imo: Optional[str] = None
    mmsi: Optional[str] = None
    active: bool = True
    notes: Optional[str] = None


@dataclass(frozen=True)
class Position:
    vessel_name: str
    latitude: float
    longitude: float
    speed_knots: Optional[float]
    course_degrees: Optional[float]
    navigational_status: str
    destination: Optional[str]
    reported_eta: Optional[str]
    position_timestamp: datetime
    source: str
    position_type: Optional[str] = None
    broad_location: Optional[str] = None
    broad_timezone: Optional[str] = None
    underway_since: Optional[datetime] = None


@dataclass(frozen=True)
class Location:
    name: str
    timezone_name: Optional[str]
    kind: str
    distance_km: Optional[float] = None


@dataclass(frozen=True)
class TimeEstimate:
    local_time: datetime
    seattle_time: datetime
    offset_minutes: int
    timezone_label: str
    approximate: bool


@dataclass(frozen=True)
class FleetData:
    cruise_line_order: Tuple[str, ...]
    vessels: Tuple[Vessel, ...]
