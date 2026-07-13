"""
Tests chatagent/tool.py's flattening and escalation logic with the real
`requests.post` call mocked out (tool._post is patched directly) — no
network access, but the canned response shape is a trimmed real response
captured from the live API for booking LH123456.
"""

from unittest.mock import patch

import tool


class FakeEvent:
    def __init__(self, author):
        self.author = author


class FakeSession:
    def __init__(self):
        self.events = []


class FakeToolContext:
    """Minimal stand-in for google.adk.tools.tool_context.ToolContext —
    tool.py only ever calls .get()/[]= on tool_context.state, plus (for
    add_luggage's confirmation gate) reads tool_context.session.events, so
    this fakes just enough of that without spinning up real ADK session
    machinery. Starts with one 'user' event already recorded, matching
    ADK's real ordering (the incoming message is appended to session
    before any tool for that turn runs — see _user_turn_index in tool.py)."""

    def __init__(self):
        self.state = {}
        self.session = FakeSession()
        self.session.events.append(FakeEvent("user"))

    def new_user_turn(self):
        """Simulates the customer's next message arriving in a new turn."""
        self.session.events.append(FakeEvent("user"))


LUGGAGE_OPTIONS_RESPONSE = {
    "bookingReference": "LH123456",
    "airline": "Jet2",
    "canAddLuggage": True,
    "currency": "GBP",
    "serviceDefinitions": [
        {"serviceDefinitionId": "BAG20", "name": "20kg Checked Bag", "type": "CHECKED_BAG", "descriptions": []},
        {"serviceDefinitionId": "BAG26", "name": "26kg Checked Bag", "type": "CHECKED_BAG", "descriptions": []},
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
                {"passengerRefIds": ["PAX-1001"], "flightSegmentRefIds": ["SEG-OUT", "SEG-IN"], "quantityAvailable": 1},
                {"passengerRefIds": ["PAX-1002"], "flightSegmentRefIds": ["SEG-OUT", "SEG-IN"], "quantityAvailable": 1},
            ],
        },
        {
            "ancillaryServiceId": "ANC-BAG26",
            "ancillaryServiceDid": "MOCK-ANC-BAG26",
            "serviceDefinitionRefId": "BAG26",
            "unitPrice": 55,
            "currency": "GBP",
            "selectionOptions": [
                {"passengerRefIds": ["PAX-1001"], "flightSegmentRefIds": ["SEG-OUT", "SEG-IN"], "quantityAvailable": 0},
            ],
        },
    ],
    "luggagePolicy": "Luggage can be added up to 48 hours before departure.",
}


def test_get_luggage_options_flattens_per_passenger_and_skips_unavailable():
    ctx = FakeToolContext()
    with patch("tool._post", return_value=(200, LUGGAGE_OPTIONS_RESPONSE)):
        result = tool.get_luggage_options("LH123456", ctx)

    option_ids = {o["option_id"] for o in result["options"]}
    # Both passengers get the 20kg bag...
    assert "ANC-BAG20::PAX-1001" in option_ids
    assert "ANC-BAG20::PAX-1002" in option_ids
    # ...but the 26kg bag has quantityAvailable=0, so it's excluded entirely.
    assert "ANC-BAG26::PAX-1001" not in option_ids
    assert len(result["options"]) == 2

    # add_luggage needs the full item spec cached under the same option_id.
    cached = ctx.state[tool._OPTIONS_CATALOG_STATE_KEY]["ANC-BAG20::PAX-1001"]
    assert cached["serviceDefinitionId"] == "BAG20"
    assert cached["passengerRefIds"] == ["PAX-1001"]
    assert cached["expectedPrice"] == {"amount": 38, "currency": "GBP"}


def test_add_luggage_rejects_unknown_option_id():
    ctx = FakeToolContext()  # empty catalog — nothing was ever looked up
    result = tool.add_luggage("LH123456", "ANC-BAG20::PAX-1001", ctx)
    assert result["success"] is False
    assert "get_luggage_options" in result["error"]


def test_get_booking_details_escalates_after_three_consecutive_failures():
    ctx = FakeToolContext()
    with patch("tool._post", return_value=(404, {"detail": "not found"})):
        r1 = tool.get_booking_details("ZZ999999", ctx)
        r2 = tool.get_booking_details("FAKE12345", ctx)
        r3 = tool.get_booking_details("NOTREAL99", ctx)

    assert r1["should_escalate"] is False
    assert r2["should_escalate"] is False
    assert r3["should_escalate"] is True
    assert r3["attempts"] == 3


def test_get_booking_details_success_resets_the_streak():
    ctx = FakeToolContext()
    with patch("tool._post", return_value=(404, {"detail": "not found"})):
        tool.get_booking_details("ZZ999999", ctx)
        tool.get_booking_details("FAKE12345", ctx)

    with patch("tool._post", return_value=(200, {"bookingReference": "LH123456"})):
        tool.get_booking_details("LH123456", ctx)

    with patch("tool._post", return_value=(404, {"detail": "not found"})):
        r = tool.get_booking_details("ZZ999999", ctx)

    # Streak reset by the successful lookup, so this is failure #1 again,
    # not #3 — should not escalate.
    assert r["attempts"] == 1
    assert r["should_escalate"] is False


def _looked_up_ctx():
    """A FakeToolContext with LH123456's luggage options already cached,
    as if get_luggage_options had just run — the state add_luggage's
    confirmation-gate tests start from."""
    ctx = FakeToolContext()
    with patch("tool._post", return_value=(200, LUGGAGE_OPTIONS_RESPONSE)):
        tool.get_luggage_options("LH123456", ctx)
    return ctx


def test_add_luggage_without_confirmed_does_not_add():
    ctx = _looked_up_ctx()
    with patch("tool._post") as mock_post:
        result = tool.add_luggage("LH123456", "ANC-BAG20::PAX-1001", ctx)

    mock_post.assert_not_called()
    assert result["success"] is False
    assert result["needs_confirmation"] is True
    assert result["name"] == "20kg Checked Bag"
    assert result["price"] == 38


def test_add_luggage_confirmed_in_same_turn_is_rejected():
    ctx = _looked_up_ctx()
    with patch("tool._post") as mock_post:
        tool.add_luggage("LH123456", "ANC-BAG20::PAX-1001", ctx)  # offer, turn 1
        result = tool.add_luggage("LH123456", "ANC-BAG20::PAX-1001", ctx, confirmed=True)  # same turn

    mock_post.assert_not_called()
    assert result["success"] is False
    assert result["needs_confirmation"] is True
    assert result["error"] == "not_yet_confirmed"


def test_add_luggage_confirmed_without_prior_offer_is_rejected():
    ctx = _looked_up_ctx()
    with patch("tool._post") as mock_post:
        result = tool.add_luggage("LH123456", "ANC-BAG20::PAX-1001", ctx, confirmed=True)

    mock_post.assert_not_called()
    assert result["success"] is False
    assert result["needs_confirmation"] is True


def test_add_luggage_confirmed_in_a_later_turn_succeeds():
    ctx = _looked_up_ctx()
    with patch("tool._post", return_value=(200, {"bookingReference": "LH123456"})) as mock_post:
        tool.add_luggage("LH123456", "ANC-BAG20::PAX-1001", ctx)  # offer, turn 1
        ctx.new_user_turn()  # customer replies "yes" — turn 2
        result = tool.add_luggage("LH123456", "ANC-BAG20::PAX-1001", ctx, confirmed=True)

    mock_post.assert_called_once()
    assert result == {"bookingReference": "LH123456"}


def test_add_luggage_offer_is_consumed_after_a_real_attempt():
    """A second confirmed=True call for the same option_id, without a
    fresh offer in between, must be rejected even in a later turn — the
    pending confirmation is consumed the moment a real add is attempted,
    not left reusable."""
    ctx = _looked_up_ctx()
    with patch("tool._post", return_value=(422, {"detail": {"message": "Item already added"}})):
        tool.add_luggage("LH123456", "ANC-BAG20::PAX-1001", ctx)  # offer, turn 1
        ctx.new_user_turn()
        tool.add_luggage("LH123456", "ANC-BAG20::PAX-1001", ctx, confirmed=True)  # turn 2, fails

    with patch("tool._post") as mock_post:
        ctx.new_user_turn()
        result = tool.add_luggage("LH123456", "ANC-BAG20::PAX-1001", ctx, confirmed=True)  # turn 3, no fresh offer

    mock_post.assert_not_called()
    assert result["needs_confirmation"] is True
