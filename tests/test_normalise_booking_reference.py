"""
Both chatagent/tool.py and voiceagent/luggage_api.py carry their own copy
of normalise_booking_reference (see DESIGN_NOTES.md for why they're not
shared) — tested identically here so the two copies can't silently drift
apart.
"""

import pytest

import luggage_api as voice_tool
import tool as chat_tool

CASES = [
    ("LH123456", "LH123456"),
    ("lov2600001", "LOV2600001"),
    ("  abc12345  ", "ABC12345"),
    ("LH-123456", "LH-123456"),
    ("my booking reference is LOV2600002, I want to add luggage", "LOV2600002"),
    ("", None),
    ("abcd", None),  # under 5 chars
    ("a" * 25, None),  # over 20 chars
    ("I want to add luggage please", None),  # prose, nothing reference-shaped
    ("<script>alert(1)</script>", None),  # unsafe characters
    ("ABCDEF", "ABCDEF"),  # standalone all-letter reference is accepted
    # Real failure from live voice testing: speech-to-text renders a spoken
    # reference as individually spelled-out letters/digits, not "LH654321".
    ("L h six five four three two one", "LH654321"),
    ("l h 6 5 4 3 2 1", "LH654321"),  # mixed spelled-digits and numerals
]


@pytest.mark.parametrize("raw, expected", CASES)
def test_chat_tool_normalise(raw, expected):
    assert chat_tool.normalise_booking_reference(raw) == expected


@pytest.mark.parametrize("raw, expected", CASES)
def test_voice_tool_normalise(raw, expected):
    assert voice_tool.normalise_booking_reference(raw) == expected
