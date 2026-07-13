"""
Same coverage as test_chatagent_tool.py, but for voiceagent/luggage_api.py —
confirms the call_id-keyed dict state (used since Retell calls have no ADK
Runner/session) behaves the same as chatagent's ADK-session-state version.
"""

from unittest.mock import patch

import luggage_api

LUGGAGE_OPTIONS_RESPONSE = {
    "bookingReference": "LH123456",
    "airline": "Jet2",
    "canAddLuggage": True,
    "currency": "GBP",
    "serviceDefinitions": [
        {"serviceDefinitionId": "BAG20", "name": "20kg Checked Bag", "type": "CHECKED_BAG", "descriptions": []},
    ],
    "baggageAllowanceDefinitions": [],
    "ancillaryServices": [
        {
            "ancillaryServiceId": "ANC-BAG20",
            "ancillaryServiceDid": "MOCK-ANC-BAG20",
            "serviceDefinitionRefId": "BAG20",
            "unitPrice": 38,
            "currency": "GBP",
            "selectionOptions": [
                {"passengerRefIds": ["PAX-1002"], "flightSegmentRefIds": ["SEG-OUT", "SEG-IN"], "quantityAvailable": 1},
            ],
        },
    ],
    "luggagePolicy": "Luggage can be added up to 48 hours before departure.",
}


def test_get_luggage_options_caches_catalog_per_call_id():
    call_id = "test_call_A"
    with patch("luggage_api._post", return_value=(200, LUGGAGE_OPTIONS_RESPONSE)):
        result = luggage_api.get_luggage_options(call_id, "LH123456")

    assert result["options"][0]["option_id"] == "ANC-BAG20::PAX-1002"
    assert call_id in luggage_api._options_catalog_by_call
    luggage_api.cleanup_call(call_id)
    assert call_id not in luggage_api._options_catalog_by_call


def test_get_booking_details_escalation_is_scoped_per_call_id():
    call_a, call_b = "test_call_B1", "test_call_B2"
    with patch("luggage_api._post", return_value=(404, {"detail": "not found"})):
        luggage_api.get_booking_details(call_a, "ZZ999999")
        luggage_api.get_booking_details(call_a, "FAKE12345")
        r_a3 = luggage_api.get_booking_details(call_a, "NOTREAL99")
        # A fresh call_id (e.g. a different phone call) starts its own count.
        r_b1 = luggage_api.get_booking_details(call_b, "ZZ999999")

    assert r_a3["should_escalate"] is True
    assert r_b1["should_escalate"] is False
    assert r_b1["attempts"] == 1

    luggage_api.cleanup_call(call_a)
    luggage_api.cleanup_call(call_b)


def test_add_luggage_without_confirmed_does_not_add():
    call_id = "test_call_C1"
    with patch("luggage_api._post", return_value=(200, LUGGAGE_OPTIONS_RESPONSE)):
        luggage_api.get_luggage_options(call_id, "LH123456")

    with patch("luggage_api._post") as mock_post:
        result = luggage_api.add_luggage(call_id, "LH123456", "ANC-BAG20::PAX-1002")

    mock_post.assert_not_called()
    assert result["needs_confirmation"] is True
    assert result["price"] == 38

    luggage_api.cleanup_call(call_id)


def test_add_luggage_confirmed_too_soon_after_offer_is_rejected():
    call_id = "test_call_C2"
    with patch("luggage_api._post", return_value=(200, LUGGAGE_OPTIONS_RESPONSE)):
        luggage_api.get_luggage_options(call_id, "LH123456")

    with patch("luggage_api.time.monotonic", return_value=100.0):
        luggage_api.add_luggage(call_id, "LH123456", "ANC-BAG20::PAX-1002")  # offer at t=100

    with patch("luggage_api.time.monotonic", return_value=100.5):  # only 0.5s later
        with patch("luggage_api._post") as mock_post:
            result = luggage_api.add_luggage(call_id, "LH123456", "ANC-BAG20::PAX-1002", confirmed=True)

    mock_post.assert_not_called()
    assert result["needs_confirmation"] is True
    assert result["error"] == "not_yet_confirmed"

    luggage_api.cleanup_call(call_id)


def test_add_luggage_confirmed_after_gap_succeeds():
    call_id = "test_call_C3"
    with patch("luggage_api._post", return_value=(200, LUGGAGE_OPTIONS_RESPONSE)):
        luggage_api.get_luggage_options(call_id, "LH123456")

    with patch("luggage_api.time.monotonic", return_value=200.0):
        luggage_api.add_luggage(call_id, "LH123456", "ANC-BAG20::PAX-1002")  # offer at t=200

    with patch("luggage_api.time.monotonic", return_value=210.0):  # 10s later
        with patch("luggage_api._post", return_value=(200, {"bookingReference": "LH123456"})) as mock_post:
            result = luggage_api.add_luggage(call_id, "LH123456", "ANC-BAG20::PAX-1002", confirmed=True)

    mock_post.assert_called_once()
    # option_id is echoed back on success — same reasoning as chatagent/tool.py.
    assert result == {"bookingReference": "LH123456", "option_id": "ANC-BAG20::PAX-1002"}

    luggage_api.cleanup_call(call_id)
