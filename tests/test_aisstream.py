from datetime import timezone

import pytest

from fleet_receipt.models import Vessel
from fleet_receipt.providers.aisstream import (
    AISStreamError,
    build_subscription,
    position_from_message,
    static_data_from_message,
)


def test_subscription_filters_to_position_reports_and_mmsis():
    subscription = build_subscription("secret", ["245206000", "244830547"])

    assert subscription["APIKey"] == "secret"
    assert subscription["BoundingBoxes"] == [[[-90.0, -180.0], [90.0, 180.0]]]
    assert subscription["FiltersShipMMSI"] == ["245206000", "244830547"]
    assert subscription["FilterMessageTypes"] == [
        "PositionReport",
        "StandardClassBPositionReport",
        "ExtendedClassBPositionReport",
        "ShipStaticData",
    ]


def test_empty_api_key_is_rejected():
    with pytest.raises(AISStreamError, match="missing or empty"):
        build_subscription(" ", ["245206000"])


def test_position_report_maps_mmsi_to_configured_vessel():
    vessel = Vessel("Holland America Line", "Eurodam", mmsi="245206000")
    message = {
        "MessageType": "PositionReport",
        "Message": {
            "PositionReport": {
                "UserID": 245206000,
                "Valid": True,
                "Latitude": 47.61,
                "Longitude": -122.34,
                "Sog": 12.5,
                "Cog": 275.2,
                "NavigationalStatus": 0,
            }
        },
        "MetaData": {"time_utc": "2026-07-23 12:34:56.123456 +0000 UTC"},
    }

    position = position_from_message(message, {"245206000": vessel})

    assert position is not None
    assert position.vessel_name == "Eurodam"
    assert position.latitude == 47.61
    assert position.longitude == -122.34
    assert position.speed_knots == 12.5
    assert position.course_degrees == 275.2
    assert position.navigational_status == "Under way"
    assert position.position_timestamp.tzinfo == timezone.utc
    assert position.source == "AISstream.io"


def test_unconfigured_mmsi_is_ignored():
    message = {
        "MessageType": "PositionReport",
        "Message": {
            "PositionReport": {
                "UserID": 999999999,
                "Latitude": 1,
                "Longitude": 2,
            }
        },
    }

    assert position_from_message(message, {}) is None


@pytest.mark.parametrize(
    "message_type",
    ["StandardClassBPositionReport", "ExtendedClassBPositionReport"],
)
def test_class_b_position_reports_are_accepted(message_type):
    vessel = Vessel("Holland America Line", "Eurodam", mmsi="245206000")
    message = {
        "MessageType": message_type,
        "Message": {
            message_type: {
                "UserID": 245206000,
                "Valid": True,
                "Latitude": 47.62,
                "Longitude": -122.35,
                "Sog": 8.2,
                "Cog": 90.0,
            }
        },
        "MetaData": {"time_utc": "2026-08-06T15:30:00Z"},
    }

    position = position_from_message(message, {"245206000": vessel})

    assert position is not None
    assert position.latitude == 47.62
    assert position.speed_knots == 8.2


def test_static_data_extracts_destination_and_eta():
    message = {
        "MessageType": "ShipStaticData",
        "Message": {
            "ShipStaticData": {
                "UserID": 245206000,
                "Valid": True,
                "Destination": "ROTTERDAM@@@@",
                "Eta": {"Month": 7, "Day": 26, "Hour": 7, "Minute": 0},
            }
        },
        "MetaData": {"time_utc": "2026-07-23 12:00:00 +0000 UTC"},
    }

    mmsi, details = static_data_from_message(message)

    assert mmsi == "245206000"
    assert details["destination"] == "ROTTERDAM"
    assert details["reported_eta"] == "2026-07-26T07:00:00+00:00"
