"""
main.py
=======
FastAPI wrapper around the Luggage Support Assistant (agent.py, built on
Google ADK). Exposes a /chat endpoint that keeps a per-session ADK session
alive, so a frontend (or curl/Postman) can drive the conversation over HTTP
instead of agent.py's built-in terminal loop.

Talks to the real loveholidays luggage API via tool.py — see that file's
BASE_URL.

Run (either works):
    uvicorn main:app --reload --port 8001
    python main.py
"""

import logging
import uuid
from typing import Optional

from dotenv import load_dotenv

load_dotenv()  # must run before `agent` is imported, since agent.py builds the LiteLlm/Groq client at import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent import APP_NAME, build_runner, send_message

logger = logging.getLogger(__name__)

app = FastAPI(title="Luggage Support Chat Agent")

runner = build_runner()

# Tracks which (user_id, session_id) pairs have already been created in the
# ADK session service, keyed by our own session_id.
KNOWN_SESSIONS: set[str] = set()


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    # Raw result of every tool call made this turn (get_booking_details,
    # get_luggage_options, add_luggage, escalate_to_human — see tool.py for
    # each one's exact shape), so a UI can render real luggage-option
    # cards/booking details/confirmation state instead of re-parsing the
    # assistant's prose reply.
    tool_results: list[dict] = []


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    logger.info("[%s] <- %r", session_id, request.message)

    if session_id not in KNOWN_SESSIONS:
        await runner.session_service.create_session(
            app_name=APP_NAME, user_id=session_id, session_id=session_id
        )
        KNOWN_SESSIONS.add(session_id)

    try:
        reply, tool_results = await send_message(
            runner, user_id=session_id, session_id=session_id, text=request.message
        )
    except Exception as exc:
        logger.exception("[%s] agent/model call failed", session_id)
        raise HTTPException(status_code=502, detail=f"Agent/model call failed: {exc}") from exc

    logger.info("[%s] -> %r", session_id, reply)
    return ChatResponse(session_id=session_id, reply=reply, tool_results=tool_results)


@app.post("/chat/reset")
async def reset_chat(session_id: str):
    existed = session_id in KNOWN_SESSIONS
    if existed:
        await runner.session_service.delete_session(
            app_name=APP_NAME, user_id=session_id, session_id=session_id
        )
        KNOWN_SESSIONS.discard(session_id)
    return {"reset": existed, "session_id": session_id}


@app.get("/")
def root():
    return {"status": "ok", "active_sessions": len(KNOWN_SESSIONS)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8001)
