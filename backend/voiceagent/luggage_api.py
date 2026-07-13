"""
luggage_api.py
==============
Bridge between the Retell voice agent (main.py's /functions endpoint) and
the real loveholidays luggage API — the voice-call counterpart to
../chatagent/tool.py. Same underlying API and business logic (soft booking
reference validation, per-passenger luggage options, 3-strikes escalation),
but state is keyed by Retell's call_id (a plain in-memory dict) instead of
ADK's session state, since a live phone/web call has no ADK Runner.
"""

import logging
import re
import time

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://adrian-thompson-loveholidays-ccai-luggage-mock-api.hf.space"
TIMEOUT = 10

MAX_LOOKUP_ATTEMPTS = 3

# Minimum real time that must pass between offering an option and a
# confirmed=True call for it — see add_luggage for why this exists and why
# it's a weaker (time-based) proxy here than chatagent/tool.py's
# turn-index gate.
MIN_CONFIRMATION_GAP_SECONDS = 2.0

# Per-call state, keyed by Retell's call_id. Small and short-lived (one
# entry per concurrent call) so an unbounded plain dict is fine here.
_attempts_by_call: dict[str, int] = {}
_options_catalog_by_call: dict[str, dict[str, dict]] = {}
_last_booking_ref_by_call: dict[str, str] = {}
_escalated_bookings_by_call: dict[str, set[str]] = {}
_pending_confirmations_by_call: dict[str, dict[str, float]] = {}

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
    (None, "<description of the failure>").
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

    Same rules as chatagent/tool.py's version — no fixed format required,
    the real API is the source of truth; this just filters out input that
    obviously isn't a reference at all.
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

    for tok in candidates:
        if any(c.isalpha() for c in tok) and any(c.isdigit() for c in tok):
            return tok

    if len(cleaned.split()) <= 2 and len(candidates) == 1:
        return candidates[0]
    return None


def get_booking_details(call_id: str, booking_reference: str) -> dict:
    """Looks up a booking by reference. Tracks failed-attempt count per call_id."""
    attempts = _attempts_by_call.get(call_id, 0)

    def _record_failure(reason: str) -> dict:
        nonlocal attempts
        attempts += 1
        _attempts_by_call[call_id] = attempts
        logger.info("[%s] get_booking_details failure #%s: %s", call_id, attempts, reason)
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
    _attempts_by_call[call_id] = 0
    _last_booking_ref_by_call[call_id] = normalised
    return body


def get_luggage_options(call_id: str, booking_reference: str) -> dict:
    """Gets available luggage options, flattened to one option per (bag type, passenger)."""
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

    _options_catalog_by_call[call_id] = catalog

    return {
        "booking_reference": booking_reference,
        "airline": body.get("airline"),
        "can_add_luggage": body.get("canAddLuggage"),
        "luggage_policy": body.get("luggagePolicy"),
        "options": flat_options,
    }


def _is_duplicate_item_conflict(status: int | None, body) -> bool:
    """Heuristic for "this exact item was already added to the booking" —
    same reasoning as chatagent/tool.py's version: the real API reports
    this as a 422 with a nested detail.error/message rather than a
    dedicated status code, so this matches on the message text rather
    than trusting the status code alone.
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


def add_luggage(
    call_id: str, booking_reference: str, selected_option_id: str, confirmed: bool = False
) -> dict:
    """Adds a chosen (bag type, passenger) option, looked up from the cached
    catalog. Requires two separate calls:

    1. Call with confirmed left False once the customer has named an
       option. This does NOT add anything — it returns the exact item,
       passenger, and price. Read those back to the customer and ask them
       to confirm, then wait for their spoken reply.
    2. Only after they say yes, call again with confirmed=True to
       actually add it.

    Unlike chatagent/tool.py's version of this gate (which can detect real
    conversation-turn boundaries via ADK session events), this has no
    visibility into Retell's own conversation loop, so it uses a minimum
    elapsed time since the offer (MIN_CONFIRMATION_GAP_SECONDS) as the
    best available proxy for "the customer was actually asked and had
    time to answer" — weaker than the chat agent's guarantee, but still a
    real, code-enforced floor rather than trusting the model's word alone.

    On a duplicate-item conflict, the result includes remaining_options —
    other valid options still available on this booking."""
    catalog = _options_catalog_by_call.get(call_id, {})
    item = catalog.get(selected_option_id)
    if item is None:
        logger.warning("[%s] add_luggage got unknown option_id=%r", call_id, selected_option_id)
        return {
            "success": False,
            "error": "That option_id isn't recognized. Call get_luggage_options again to get current option_ids.",
        }

    pending = _pending_confirmations_by_call.setdefault(call_id, {})

    if not confirmed:
        pending[selected_option_id] = time.monotonic()
        return {
            "success": False,
            "needs_confirmation": True,
            "option_id": selected_option_id,
            "name": item.get("name", item["serviceDefinitionId"]),
            "price": item["expectedPrice"]["amount"],
            "currency": item["expectedPrice"]["currency"],
            "passenger_ref_ids": item["passengerRefIds"],
            "message": (
                "Not added yet. Read back this exact item, passenger, and price to "
                "the customer and ask them to confirm, then wait for their spoken "
                "reply — do not call add_luggage again until they respond. Only "
                "then call add_luggage with confirmed=true."
            ),
        }

    offered_at = pending.get(selected_option_id)
    if offered_at is None or (time.monotonic() - offered_at) < MIN_CONFIRMATION_GAP_SECONDS:
        logger.warning(
            "[%s] add_luggage confirmed=True for %s rejected — offered_at=%s",
            call_id,
            selected_option_id,
            offered_at,
        )
        return {
            "success": False,
            "needs_confirmation": True,
            "error": "not_yet_confirmed",
            "message": (
                "You must read back this exact item, passenger, and price to the "
                "customer and get their explicit spoken yes before calling "
                "add_luggage with confirmed=true. Call add_luggage with confirmed "
                "left as false first, read its summary to the customer, and wait "
                "for their answer before trying again."
            ),
        }

    # Gate passed — consume it so a later confirmed=True call for the same
    # option_id needs a fresh offer, even if this attempt fails below.
    pending.pop(selected_option_id, None)

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

    return body


def escalate_to_human(call_id: str, reason: str, booking_reference: str = "") -> dict:
    """Hands the conversation over to a human agent. Falls back to the last
    booking reference looked up on this call if none is given, and skips a
    duplicate /escalations POST if that booking was already escalated
    earlier on this call — same reasoning as chatagent/tool.py's version:
    a prompt instruction alone isn't reliable for "don't re-escalate the
    same booking," confirmed by testing."""
    if not booking_reference:
        booking_reference = _last_booking_ref_by_call.get(call_id, "")

    escalated = _escalated_bookings_by_call.setdefault(call_id, set())
    if booking_reference and booking_reference in escalated:
        logger.info("[%s] escalate_to_human: %s already escalated this call, skipping duplicate", call_id, booking_reference)
        return {
            "escalated": True,
            "already_escalated": True,
            "booking_reference": booking_reference,
            "reason": reason,
            "message": (
                "This booking was already escalated to a human agent earlier in this "
                "call. Do not escalate again — answer the customer's question directly "
                "using what you already know, or remind them a human agent will be in "
                "touch."
            ),
        }

    status, body = _post("/escalations", {"bookingReference": booking_reference, "reason": reason})

    if booking_reference:
        escalated.add(booking_reference)

    if status is None or status >= 400:
        logger.warning("Escalation API failed (status=%s): %s", status, body)
        return {
            "escalated": True,
            "booking_reference": booking_reference,
            "reason": reason,
            "message": "Escalation needed, but escalation API failed.",
        }

    return body


def cleanup_call(call_id: str) -> None:
    """Drops cached state for a call once it ends, so memory doesn't grow unbounded."""
    _attempts_by_call.pop(call_id, None)
    _options_catalog_by_call.pop(call_id, None)
    _last_booking_ref_by_call.pop(call_id, None)
    _escalated_bookings_by_call.pop(call_id, None)
    _pending_confirmations_by_call.pop(call_id, None)
