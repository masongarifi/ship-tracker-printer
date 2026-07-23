import pytest

from fleet_receipt.providers.marinetraffic import MarineTrafficNotConfigured, MarineTrafficProvider


def test_marinetraffic_stub_does_not_invent_an_api(fleet):
    with pytest.raises(MarineTrafficNotConfigured, match="official API documentation"):
        MarineTrafficProvider().fetch_positions(fleet.vessels)

