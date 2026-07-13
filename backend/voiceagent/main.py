

import asyncio
import json
import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from retell import Retell

import luggage_api

logger = logging.getLogger(__name__)

# Retell's browser SDK only exposes the spoken transcript to the frontend —
# the actual tool-call results (booking details, luggage options, add
# results) are produced server-side, right here in /functions, and never
# routed through the browser at all. So a voice-mode UI that wants real
# luggage-option cards (not guessed from transcript text) needs a separate
# channel: this in-memory per-call_id queue, drained by the SSE endpoint
# below, that the browser subscribes to once a call starts.
_call_event_queues: dict[str, asyncio.Queue] = {}


def _queue_for(call_id: str) -> asyncio.Queue:
    return _call_event_queues.setdefault(call_id, asyncio.Queue())

# Paste these parameter schemas into each Custom Function's dashboard config
# (Functions > + Add > Custom Function > Parameters schema). Name each
# function exactly as the dict key below — that's the `name` value Retell
# will send us, which is how /functions knows which one to run.
FUNCTION_SCHEMAS = {
    "get_booking_details": {
        "type": "object",
        "properties": {
            "booking_reference": {
                "type": "string",
                "description": "The booking reference the customer gave, in whatever form they said it.",
            }
        },
        "required": ["booking_reference"],
    },
    "get_luggage_options": {
        "type": "object",
        "properties": {
            "booking_reference": {
                "type": "string",
                "description": "The booking reference, as confirmed by get_booking_details.",
            }
        },
        "required": ["booking_reference"],
    },
    "add_luggage": {
        "type": "object",
        "properties": {
            "booking_reference": {
                "type": "string",
                "description": "The booking reference, as confirmed by get_booking_details.",
            },
            "selected_option_id": {
                "type": "string",
                "description": "The exact option_id from get_luggage_options's options list.",
            },
            "confirmed": {
                "type": "boolean",
                "description": (
                    "Leave false (or omit) the first time to get the item/passenger/price "
                    "to read back to the customer. Only set true after the customer has "
                    "explicitly said yes in a later reply."
                ),
            },
        },
        "required": ["booking_reference", "selected_option_id"],
    },
    "escalate_to_human": {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Short internal reason for the escalation."},
            "booking_reference": {
                "type": "string",
                "description": "The booking reference in play, if any. Empty string if none.",
            },
        },
        "required": ["reason"],
    },
}

RETELL_API_KEY = os.environ.get("RETELL_API_KEY")
RETELL_AGENT_ID = os.environ.get("RETELL_AGENT_ID")

if not RETELL_API_KEY:
    raise RuntimeError("RETELL_API_KEY is missing — set it in backend/voiceagent/.env")
if not RETELL_AGENT_ID:
    raise RuntimeError("RETELL_AGENT_ID is missing — set it in backend/voiceagent/.env")

retell_client = Retell(api_key=RETELL_API_KEY)

app = FastAPI(title="Voice Agent Service")

# The frontend dev server (Vite) calls this directly rather than through a
# proxy, since /create-web-call needs to be reachable both from the browser
# dev server and, later, a deployed static frontend. Vite picks a different
# port (5174, 5175, ...) whenever the previous one is still occupied, so we
# match any localhost/127.0.0.1 port rather than hardcoding 5173.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/create-web-call")
def create_web_call():
    """Starts a new Retell web call and returns the access token the
    browser SDK needs to connect (see VoiceWidget.tsx)."""
    logger.info("-> create_web_call agent_id=%s", RETELL_AGENT_ID)
    try:
        call = retell_client.call.create_web_call(agent_id=RETELL_AGENT_ID)
    except Exception as exc:
        logger.exception("create_web_call failed")
        raise HTTPException(status_code=502, detail=f"Retell create_web_call failed: {exc}") from exc

    logger.info("<- create_web_call call_id=%s", call.call_id)
    return {"access_token": call.access_token, "call_id": call.call_id}


@app.get("/functions/schema")
def functions_schema():
    """Convenience endpoint: returns the parameter schemas to paste into
    each Custom Function's dashboard config."""
    return FUNCTION_SCHEMAS


@app.post("/functions")
async def custom_function(request: Request):
    """Single Custom Function webhook for all four luggage functions,
    dispatched by the `name` field Retell sends alongside `call` and `args`.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Retell-Signature", "")

    valid = retell_client.verify(raw_body.decode("utf-8"), RETELL_API_KEY, signature)
    if not valid:
        logger.warning("rejected /functions call with invalid signature")
        raise HTTPException(status_code=401, detail="Invalid Retell webhook signature")

    payload = await request.json()
    name = payload.get("name")
    args = payload.get("args", {})
    call_id = payload.get("call", {}).get("call_id", "")

    logger.info("[%s] function call name=%s args=%s", call_id, name, args)

    if name == "get_booking_details":
        result = luggage_api.get_booking_details(call_id, args.get("booking_reference", ""))
    elif name == "get_luggage_options":
        result = luggage_api.get_luggage_options(call_id, args.get("booking_reference", ""))
    elif name == "add_luggage":
        result = luggage_api.add_luggage(
            call_id,
            args.get("booking_reference", ""),
            args.get("selected_option_id", ""),
            args.get("confirmed", False),
        )
    elif name == "escalate_to_human":
        result = luggage_api.escalate_to_human(call_id, args.get("reason", ""), args.get("booking_reference", ""))
    elif name is None:
        # Almost always means the Custom Function's "Payload: args only"
        # toggle is on in the Retell dashboard, which strips out `name`/
        # `call` and sends just the arguments — this dispatcher can't route
        # without `name`, so that toggle must stay off for all four functions.
        logger.warning("[%s] /functions payload missing 'name' (payload=%s)", call_id, payload)
        result = {
            "error": (
                "Request is missing a 'name' field. In the Retell dashboard, make sure "
                "'Payload: args only' is disabled for this Custom Function."
            )
        }
    else:
        logger.warning("[%s] unknown function name=%r", call_id, name)
        result = {"error": f"Unknown function '{name}'"}

    if call_id and name:
        _queue_for(call_id).put_nowait({"name": name, "result": result})

    return result


@app.get("/functions/stream/{call_id}")
async def stream_function_calls(call_id: str):
    """Server-sent events of this call's tool-call results — see the
    _call_event_queues comment above for why this exists. The browser
    voice widget opens one of these per call to render real luggage-option
    cards/booking details from the same data the voice agent's tools
    returned, instead of guessing from the spoken transcript."""
    queue = _queue_for(call_id)

    async def event_stream():
        try:
            while True:
                item = await queue.get()
                yield f"data: {json.dumps(item)}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/webhook")
async def retell_webhook(request: Request):
    """Receives call lifecycle events from Retell.

    Signature verification uses the exact raw request body Retell signed —
    re-serializing the parsed JSON would change key order/whitespace and
    break the HMAC check, so we verify against request.body() before ever
    parsing it.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Retell-Signature", "")

    valid = retell_client.verify(raw_body.decode("utf-8"), RETELL_API_KEY, signature)
    if not valid:
        logger.warning("rejected webhook with invalid signature")
        raise HTTPException(status_code=401, detail="Invalid Retell webhook signature")

    payload = await request.json()
    event = payload.get("event")
    call = payload.get("call", {})
    call_id = call.get("call_id")

    if event == "call_started":
        logger.info("call_started call_id=%s", call_id)
    elif event == "call_ended":
        logger.info("call_ended call_id=%s status=%s", call_id, call.get("call_status"))
        if call_id:
            luggage_api.cleanup_call(call_id)
            _call_event_queues.pop(call_id, None)
    elif event == "call_analyzed":
        logger.info(
            "call_analyzed call_id=%s summary=%s",
            call_id,
            call.get("call_analysis", {}).get("call_summary"),
        )
    else:
        logger.info("unrecognized event=%r payload=%s", event, payload)

    return {"received": True}


@app.get("/")
def root():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8002)
