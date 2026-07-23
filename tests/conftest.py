from datetime import datetime, timezone

import pytest

from fleet_receipt.config import load_fleet
from fleet_receipt.providers.fixtures import FixturePositionProvider


@pytest.fixture
def fleet():
    return load_fleet()


@pytest.fixture
def positions(fleet):
    return FixturePositionProvider().fetch_positions(fleet.vessels)


@pytest.fixture
def report_time():
    return datetime(2026, 7, 22, 23, 18, tzinfo=timezone.utc)

