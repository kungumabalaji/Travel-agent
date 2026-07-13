"""
tool.py
=======
Bridge between the chat agent (agent.py, built on Google ADK) and the real
loveholidays luggage API (a hosted mock, standing in for the production
booking system). These are plain Python functions passed straight into the
ADK Agent's `tools=[...]` — ADK uses each function's docstring as the tool
description shown to the model, and its type hints to build the call
schema (a `tool_context: ToolContext` parameter is auto-injected by ADK and
never shown to the model — see get_booking_details below).

Every outbound API call goes through `_post`, which logs the request and
response and turns network/HTTP failures into a normal error dict instead
of an unhandled exception — a tool that raises kills the whole agent turn
(surfaces to the customer as a 502), whereas a returned error dict lets the
model apologize and escalate per the system prompt's error-handling rules.
"""

import logging
import re

import requests
from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)

BASE_URL = "https://adrian-thompson-loveholidays-ccai-luggage-mock-api.hf.space"
TIMEOUT = 10

MAX_LOOKUP_ATTEMPTS = 3
_ATTEMPTS_STATE_KEY = "booking_lookup_failed_attempts"
_OPTIONS_CATALOG_STATE_KEY = "luggage_options_catalog"
_LAST_BOOKING_REF_STATE_KEY = "last_booking_reference"
_ESCALATED_BOOKINGS_STATE_KEY = "escalated_booking_references"
_PENDING_CONFIRMATIONS_STATE_KEY = "pending_luggage_confirmations"

_UNSAFE_CHARS = re.compile(r"[^A-Z0-9\-\s.,!?']")
_TOKEN = re.compile(r"[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?")

_NUMBER_WORDS = {
    "ZERO": "0", "OH": "0", "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4",
    "FIVE": "5", "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9",
}


def _collapse_spelled_out_tokens(text: str) -> str:
    """Collapses runs of individually-spoken letters/digits — how speech-to-
    text renders a spoken reference, e.g. "L H six five four three two one"
    — into one contiguous token ("LH654321") before the usual extraction
    logic runs. Ordinary words are left untouched.
    """
    words = text.split()
    collapsed: list[str] = []
    run: list[str] = []

    def flush():
        if len(run) >= 2:  # a lone letter/digit-word isn't a spelled-out run
            collapsed.append("".join(run))
        else:
            collapsed.extend(run)
        run.clear()

    for word in words:
        upper = word.upper()
        if upper in _NUMBER_WORDS:
            run.append(_NUMBER_WORDS[upper])
        elif len(upper) == 1 and upper.isalnum():
            run.append(upper)
        else:
            flush()
            collapsed.append(word)
    flush()

    return " ".join(collapsed)


def _post(endpoint: str, payload: dict) -> tuple[int | None, dict | str]:
    """POSTs to the luggage API, logging the call and its outcome.

    Returns (status_code, parsed_json_or_text). Never raises — a
    connection failure/timeout is logged and reported back as
    (None, "<description of the failure>") so callers can turn it into a
    normal tool-result error dict.
    """
    url = f"{BASE_URL}{endpoint}"
    logger.info("-> POST %s payload=%s", endpoint, payload)

    try:
        resp = requests.post(url, json=payload, timeout=TIMEOUT)
    except requests.RequestException as exc:
        logger.exception("POST %s failed to connect", endpoint)
        return None, f"Could not reach the booking service: {exc}"

    try:
        body = resp.json()
    except ValueError:
        body = resp.text

    if resp.status_code >= 400:
        logger.warning("<- POST %s status=%s body=%s", endpoint, resp.status_code, body)
    else:
        logger.info("<- POST %s status=%s", endpoint, resp.status_code)

    return resp.status_code, body


def normalise_booking_reference(text: str) -> str | None:
    """Extracts and softly validates a likely booking reference from free text.

    Trims/uppercases the input and pulls out a plausible alphanumeric token
    rather than enforcing one fixed format (e.g. "LH" + 6 digits) — the real
    API is the source of truth for whether a reference actually exists, so
    this only needs to filter out input that obviously isn't a reference at
    all (empty, way too short/long, unsafe characters, prose with nothing
    reference-shaped in it) before spending an API call on it.

    Returns the cleaned reference (A-Z, 0-9, hyphen; 5-20 chars), or None if
    nothing plausible was found.
    """
    if not text:
        return None

    text = _collapse_spelled_out_tokens(text)
    cleaned = text.strip().upper()
    if not cleaned or len(cleaned) > 200:
        return None

    if _UNSAFE_CHARS.search(cleaned):
        return None

    candidates = [tok for tok in _TOKEN.findall(cleaned) if 5 <= len(tok) <= 20]
    if not candidates:
        return None

    # Every real format we've seen (LH123456, LOV2600001, ABC12345,
    # LH-123456) mixes letters and digits, so prefer a token like that when
    # extracting from a full sentence.
    for tok in candidates:
        if any(c.isalpha() for c in tok) and any(c.isdigit() for c in tok):
            return tok

    # No digit+letter candidate found — only accept an all-letters/all-digits
    # token if it's essentially the whole message, not a word picked out of
    # an unrelated sentence (e.g. "LUGGAGE" out of "I want to add luggage").
    if len(cleaned.split()) <= 2 and len(candidates) == 1:
        return candidates[0]
    return None


def get_booking_details(booking_reference: str, tool_context: ToolContext) -> dict:
    """Look up a loveholidays booking by its reference number.

    Returns whether the booking exists, its passengers/flight details, and
    whether it can be modified. Always call this first when the customer
    gives a booking reference. Soft-validates and normalizes the reference
    before calling the API — it does not require any specific format, since
    the API is the source of truth for whether a reference is real.

    If the result includes should_escalate: true, immediately call
    escalate_to_human — the customer has failed 3 lookups in a row.

    Args:
        booking_reference: The booking reference the customer provided, in whatever form they gave it.
    """
    attempts = tool_context.state.get(_ATTEMPTS_STATE_KEY, 0)

    def _record_failure(reason: str) -> dict:
        nonlocal attempts
        attempts += 1
        tool_context.state[_ATTEMPTS_STATE_KEY] = attempts
        logger.info("get_booking_details failure #%s: %s", attempts, reason)
        return {
            "found": False,
            "booking_reference": booking_reference,
            "error": reason,
            "attempts": attempts,
            "should_escalate": attempts >= MAX_LOOKUP_ATTEMPTS,
        }

    normalised = normalise_booking_reference(booking_reference)
    if normalised is None:
        return _record_failure("That doesn't look like a valid booking reference.")

    status, body = _post("/booking/lookup", {"bookingReference": normalised})

    if status is None:
        return _record_failure(str(body))
    if status == 404:
        return _record_failure("Booking not found")
    if status >= 400:
        return _record_failure(f"Booking service returned an unexpected error (status {status}).")

    body["found"] = True
    # A successful lookup resets the streak — we only escalate after 3
    # *consecutive* failures, not 3 failures over the whole conversation.
    tool_context.state[_ATTEMPTS_STATE_KEY] = 0
    tool_context.state[_LAST_BOOKING_REF_STATE_KEY] = normalised
    return body


def get_luggage_options(booking_reference: str, tool_context: ToolContext) -> dict:
    """Get available luggage options for a booking.

    Only call this after get_booking_details has confirmed the booking
    exists and can be modified. Each option is scoped to ONE passenger and
    a set of flight segments — the same bag type shows up once per
    passenger it's available for, each with its own option_id. If the
    booking has multiple passengers, ask the customer which passenger(s)
    it's for (cross-reference passenger names from the earlier
    get_booking_details result) before calling add_luggage.

    Args:
        booking_reference: The booking reference, as confirmed by get_booking_details.
    """
    status, body = _post("/booking/luggage-options", {"bookingReference": booking_reference})

    if status is None:
        return {"found": False, "booking_reference": booking_reference, "options": [], "error": body}
    if status == 404:
        return {
            "found": False,
            "booking_reference": booking_reference,
            "options": [],
            "error": "No luggage options found",
        }
    if status >= 400:
        return {
            "found": False,
            "booking_reference": booking_reference,
            "options": [],
            "error": f"Booking service returned an unexpected error (status {status}).",
        }

    service_by_id = {s["serviceDefinitionId"]: s for s in body.get("serviceDefinitions", [])}
    default_currency = body.get("currency", "GBP")

    # The real API prices and books each (bag type, passenger) combination
    # as its own line item — the raw response nests that inside
    # ancillaryServices[].selectionOptions[]. We flatten it into one option
    # per passenger per bag type, and cache the full item spec (service +
    # ancillary ids, passenger/segment refs, price) needed for the real
    # add-luggage request, keyed by a simple option_id the model can just
    # echo back — it never has to reconstruct that nested shape itself.
    catalog: dict[str, dict] = {}
    flat_options = []

    for ancillary in body.get("ancillaryServices", []):
        service_def = service_by_id.get(ancillary["serviceDefinitionRefId"], {})
        name = service_def.get("name", ancillary["serviceDefinitionRefId"])
        currency = ancillary.get("currency", default_currency)

        for selection in ancillary.get("selectionOptions", []):
            if selection.get("quantityAvailable", 0) < 1:
                continue

            option_id = f"{ancillary['ancillaryServiceId']}::{'+'.join(selection['passengerRefIds'])}"
            catalog[option_id] = {
                "name": name,
                "serviceDefinitionId": ancillary["serviceDefinitionRefId"],
                "ancillaryServiceId": ancillary["ancillaryServiceId"],
                "passengerRefIds": selection["passengerRefIds"],
                "flightSegmentRefIds": selection["flightSegmentRefIds"],
                "quantity": 1,
                "expectedPrice": {"amount": ancillary["unitPrice"], "currency": currency},
            }
            flat_options.append(
                {
                    "option_id": option_id,
                    "name": name,
                    "price": ancillary["unitPrice"],
                    "currency": currency,
                    "passenger_ref_ids": selection["passengerRefIds"],
                }
            )

    tool_context.state[_OPTIONS_CATALOG_STATE_KEY] = catalog

    return {
        "booking_reference": booking_reference,
        "airline": body.get("airline"),
        "can_add_luggage": body.get("canAddLuggage"),
        "luggage_policy": body.get("luggagePolicy"),
        "options": flat_options,
    }


def _is_duplicate_item_conflict(status: int | None, body) -> bool:
    """Heuristic for "this exact item was already added to the booking" —
    the real API reports this as a 422 with a nested detail.error/message
    rather than a dedicated status code (422 is also used for other
    validation failures), so this matches on the message text rather than
    trusting the status code alone. Confirmed against a real 422 the live
    API returned: {"detail": {"error": "luggage_not_added", "message":
    "Item 1 has already been added to this booking."}}.
    """
    if status not in (409, 422):
        return False
    if not isinstance(body, dict):
        return False
    detail = body.get("detail")
    if isinstance(detail, dict):
        text = " ".join(str(v) for v in detail.values())
    elif isinstance(detail, str):
        text = detail
    else:
        text = ""
    text = text.lower()
    return "already" in text and "add" in text


def _user_turn_index(tool_context: ToolContext) -> int:
    """Counts user messages seen so far this session, including the one
    currently being processed. ADK appends the incoming user message to
    session.events before running any tools for that turn (confirmed by
    reading Runner._setup_context_for_new_invocation: "handle new message"
    is step 2, "run agent" is step 3), so this value is stable across every
    tool call within one turn and only increases once the next /chat
    request arrives. That's what makes it usable as a turn boundary: two
    add_luggage calls with the same value are in the same turn; a higher
    value on the second call means at least one more customer message
    happened in between.
    """
    return sum(1 for event in tool_context.session.events if event.author == "user")


def add_luggage(
    booking_reference: str, selected_option_id: str, tool_context: ToolContext, confirmed: bool = False
) -> dict:
    """Add a chosen luggage option to a booking. This is the ONLY way to
    confirm an option with the customer — never write your own "shall I go
    ahead?" summary from get_luggage_options's data instead of calling
    this. Requires two separate calls across two separate customer turns:

    1. As soon as the customer names an option, call this immediately with
       confirmed left as False (the default) — do not summarise the item/
       price yourself first. This call does NOT add anything; it returns
       the exact item, passenger, and price for you to relay verbatim to
       the customer, asking them to confirm (e.g. "Shall I go ahead?").
       Then STOP — that is your final response this turn. Do not call
       add_luggage again until the customer replies.
    2. Only after the customer explicitly says yes in their NEXT message,
       call add_luggage again for the same option_id with confirmed=True
       to actually add it. Skipping step 1, or calling confirmed=True in
       the same turn as step 1, is rejected — the result will tell you to
       do step 1 first and wait. If that happens, apologise briefly, redo
       step 1 for the same option now, and wait for the customer's answer
       again — don't explain the internal rejection to the customer.

    If this fails because the item was already added (a duplicate-item
    conflict), the result includes remaining_options — other valid options
    still available on this booking. Tell the customer the item was
    already added and offer those remaining options instead of escalating,
    unless remaining_options is empty.

    Args:
        booking_reference: The booking reference, as confirmed by get_booking_details.
        selected_option_id: The exact option_id string from get_luggage_options's options list — don't alter it.
        confirmed: Only True after the customer has explicitly confirmed this exact option in a message sent AFTER you presented it via a prior confirmed=False call. Defaults to False.
    """
    catalog = tool_context.state.get(_OPTIONS_CATALOG_STATE_KEY, {})
    item = catalog.get(selected_option_id)
    if item is None:
        logger.warning("add_luggage got unknown option_id=%r", selected_option_id)
        return {
            "success": False,
            "error": "That option_id isn't recognized. Call get_luggage_options again to get current option_ids.",
        }

    # Code-enforced confirmation gate: a prompt instruction to "confirm,
    # then wait for the customer's reply" was tested and not reliably
    # followed — in 3 of 4 live completions the model called add_luggage
    # immediately after the customer named an option, never asking. This
    # makes it structurally impossible to add in the same turn an option
    # was first presented, by requiring the "offer" and the "confirmed=True"
    # call to land in different customer turns (see _user_turn_index).
    current_turn = _user_turn_index(tool_context)
    pending = tool_context.state.get(_PENDING_CONFIRMATIONS_STATE_KEY, {})

    if not confirmed:
        pending[selected_option_id] = current_turn
        tool_context.state[_PENDING_CONFIRMATIONS_STATE_KEY] = pending
        return {
            "success": False,
            "needs_confirmation": True,
            "option_id": selected_option_id,
            "name": item.get("name", item["serviceDefinitionId"]),
            "price": item["expectedPrice"]["amount"],
            "currency": item["expectedPrice"]["currency"],
            "passenger_ref_ids": item["passengerRefIds"],
            "message": (
                "Not added yet. Summarise this exact item, passenger, and price to "
                "the customer and ask them to confirm, then stop and wait for their "
                "reply — do not call add_luggage again until they respond in a new "
                "message. Only then call add_luggage with confirmed=true."
            ),
        }

    offered_turn = pending.get(selected_option_id)
    if offered_turn is None or offered_turn >= current_turn:
        logger.warning(
            "add_luggage confirmed=True for %s rejected — offered_turn=%s current_turn=%s",
            selected_option_id,
            offered_turn,
            current_turn,
        )
        return {
            "success": False,
            "needs_confirmation": True,
            "error": "not_yet_confirmed",
            "message": (
                "You must present this exact item, passenger, and price to the "
                "customer and get their explicit yes in a separate message before "
                "calling add_luggage with confirmed=true. Call add_luggage with "
                "confirmed left as false first, relay its summary to the customer, "
                "and wait for their answer before trying again."
            ),
        }

    # Gate passed — this specific option_id needs a fresh offer+wait cycle
    # before it can be confirmed again, even if this attempt fails below
    # (e.g. a duplicate-item conflict), so drop it now rather than leaving
    # a stale pass that a later confirmed=True call could reuse.
    pending.pop(selected_option_id, None)
    tool_context.state[_PENDING_CONFIRMATIONS_STATE_KEY] = pending

    idempotency_key = "-".join(
        ["add-luggage", booking_reference, *item["passengerRefIds"], item["serviceDefinitionId"]]
    )

    payload = {
        "bookingReference": booking_reference,
        "idempotencyKey": idempotency_key,
        "items": [
            {
                "serviceDefinitionId": item["serviceDefinitionId"],
                "ancillaryServiceId": item["ancillaryServiceId"],
                "passengerRefIds": item["passengerRefIds"],
                "flightSegmentRefIds": item["flightSegmentRefIds"],
                "quantity": item["quantity"],
                "expectedPrice": item["expectedPrice"],
            }
        ],
    }

    status, body = _post("/booking/add-luggage", payload)

    if status is None:
        return {"success": False, "error": body}
    if status in (400, 404, 409, 422):
        error_result = {"success": False, "error": body}
        if _is_duplicate_item_conflict(status, body):
            # Handing back the remaining options as structured data, rather
            # than leaving the model to recall/reconstruct them from
            # earlier in the conversation, is what actually got this
            # followed reliably — a prose-only instruction to "offer the
            # remaining options" was tested and did not hold up, same
            # lesson as should_escalate/already_escalated above.
            error_result["remaining_options"] = [
                {
                    "option_id": opt_id,
                    "name": spec.get("name", spec["serviceDefinitionId"]),
                    "price": spec["expectedPrice"]["amount"],
                    "currency": spec["expectedPrice"]["currency"],
                    "passenger_ref_ids": spec["passengerRefIds"],
                }
                for opt_id, spec in catalog.items()
                if opt_id != selected_option_id
            ]
        return error_result
    if status >= 400:
        return {"success": False, "error": f"Booking service returned an unexpected error (status {status})."}

    # Echo the option_id back on success so a UI can remove exactly this
    # option from whatever "still available" list it's showing, instead of
    # trying to infer which one just got added from name/passenger matching.
    body["option_id"] = selected_option_id
    return body


def escalate_to_human(reason: str, tool_context: ToolContext, booking_reference: str = "") -> dict:
    """Hand the conversation over to a human agent.

    Call this for repeated invalid references, unmodifiable bookings,
    missing luggage options, tool failures, refund/removal/price-dispute
    requests, explicit requests for a human, or anything outside luggage
    support. If the result includes already_escalated: true, this booking
    was already escalated earlier in this conversation — do not call this
    again for it; just answer the customer's question directly instead.

    Args:
        reason: Short internal reason for the escalation.
        booking_reference: The booking reference in play, if any. Pass an empty string if none — the last booking reference looked up this session is used automatically as a fallback.
    """
    if not booking_reference:
        booking_reference = tool_context.state.get(_LAST_BOOKING_REF_STATE_KEY, "")

    # A prompt instruction alone isn't reliable for "don't escalate the same
    # booking twice" — same lesson as the 3-strikes counter below: LLMs
    # don't reliably track this over a conversation, confirmed by testing
    # (the model re-escalated on plain follow-up questions about an
    # already-escalated booking). So this is enforced in code: once a
    # booking_reference has been escalated this session, any further call
    # short-circuits before the duplicate /escalations POST and tells the
    # model to just answer instead.
    escalated_bookings = tool_context.state.get(_ESCALATED_BOOKINGS_STATE_KEY, set())
    if booking_reference and booking_reference in escalated_bookings:
        logger.info("escalate_to_human: %s already escalated this session, skipping duplicate", booking_reference)
        return {
            "escalated": True,
            "already_escalated": True,
            "booking_reference": booking_reference,
            "reason": reason,
            "message": (
                "This booking was already escalated to a human agent earlier in this "
                "conversation. Do not escalate again — answer the customer's question "
                "directly using what you already know, or remind them a human agent "
                "will be in touch."
            ),
        }

    status, body = _post("/escalations", {"bookingReference": booking_reference, "reason": reason})

    if booking_reference:
        escalated_bookings.add(booking_reference)
        tool_context.state[_ESCALATED_BOOKINGS_STATE_KEY] = escalated_bookings

    if status is None or status >= 400:
        logger.warning("Escalation API failed (status=%s): %s", status, body)
        return {
            "escalated": True,
            "booking_reference": booking_reference,
            "reason": reason,
            "message": "Escalation needed, but escalation API failed.",
        }

    return body
