# loveholidays Luggage Support Assistant

A conversational AI assistant that helps loveholidays customers add luggage to
an existing booking — over **text chat** and **live voice call** — backed by
a real booking API. Built for the loveholidays Conversational AI take-home
exercise.

## What's here

| Path | What it is | Tech |
|---|---|---|
| `backend/chatagent/` | Text chat agent + HTTP API | FastAPI, Google ADK, Groq (Llama 3.3 70B via LiteLLM) |
| `backend/voiceagent/` | Voice agent bridge to Retell AI | FastAPI, Retell Python SDK |
| `backend/data/` | Original synthetic dataset (reference only — see [Assumptions](#assumptions)) | — |
| `frontend/` | Demo site (loveholidays-styled) with chat + voice widgets | React, Vite, TypeScript |

Both agents talk to the same real booking API:
`https://adrian-thompson-loveholidays-ccai-luggage-mock-api.hf.space`

## Architecture

```
                         ┌───────────────────────────┐
                         │  Loveholidays Luggage API  │
                         │  (hosted, real HTTP API)   │
                         └─────────────┬─────────────┘
                                       │ booking lookup / luggage
                                       │ options / add luggage /
                                       │ escalations
                       ┌───────────────┴───────────────┐
                       │                                │
              ┌────────┴────────┐              ┌───────┴────────┐
              │  chatagent :8001 │              │ voiceagent :8002│
              │  agent.py (ADK)  │              │  main.py        │
              │  + tool.py       │              │  + luggage_api.py│
              └────────┬────────┘              └───────┬────────┘
                       │ /chat (HTTP)                   │ /functions, /webhook
                       │                                │ (Retell custom functions)
              ┌────────┴────────────────────────────────┴────────┐
              │                     frontend :5173                 │
              │      ChatWidget.tsx           VoiceWidget.tsx      │
              │   (text chat, /api proxy)   (retell-client-js-sdk) │
              └─────────────────────────────────────────────────────┘
```

- **chatagent** — a Google ADK `Agent` running Groq's `llama-3.3-70b-versatile`
  (via ADK's `LiteLlm` wrapper). Tools are plain Python functions in `tool.py`
  that ADK introspects to build the function-calling schema — no manual
  JSON-schema bookkeeping.
- **voiceagent** — doesn't run its own LLM. The actual voice agent (prompt,
  LLM, phone number) is configured in the Retell dashboard; this service
  mints web-call tokens (`/create-web-call`), serves as the four booking
  tools Retell calls mid-call (`/functions`), and receives post-call events
  (`/webhook`).
- Both agents share the same booking-API integration logic (soft reference
  validation, per-passenger luggage options, 3-strikes escalation) —
  `chatagent/tool.py` and `voiceagent/luggage_api.py` are independent copies
  adapted to each runtime's session model (see [DESIGN_NOTES.md](DESIGN_NOTES.md)
  for why they aren't shared as one module).

## Setup

Requires Python 3.12+, Node 20+, [Git Bash](https://git-scm.com/downloads)
(Windows — Mac/Linux already have a compatible shell), and API keys for
[Groq](https://console.groq.com) and [Retell AI](https://www.retellai.com).

There are **3 services** in this project — chatagent (`:8001`), voiceagent
(`:8002`), and the frontend (`:5173`) — but only **2 terminal windows** to
manage, because the two backend services are started together with one
script instead of one terminal each. That's the whole reason `run_all.sh`
exists: without it you'd need three separate open terminals, one per
process, and remembering which window is running what gets old fast. With
it, the backend is "one thing you start," the frontend is the other, and
that's the mental model this setup is built around.

### Step 1 — Open Git Bash

All commands below run in Git Bash (Windows) or your normal terminal
(Mac/Linux). Open it in the repo's root folder.

### Step 2 — One-time setup for both backend services

```bash
cd backend/chatagent
pip install -r requirements.txt
cp .env.example .env
# edit .env: set GROQ_API_KEY
cd ../voiceagent
pip install -r requirements.txt
cp .env.example .env
# edit .env: set RETELL_API_KEY and RETELL_AGENT_ID
cd ../..
```

### Step 3 — Terminal window 1: start the backend

```bash
./backend/run_all.sh   # chatagent on :8001, voiceagent on :8002 — one command, one window
```

To stop both later, run `./backend/stop_all.sh` from another terminal —
this is the tested, reliable way to stop both services. (Ctrl+C in this
same window *may* also work, but on Windows/Git Bash it was tested and
found unreliable — native Windows child processes aren't always caught by
bash's own signal handling — so don't depend on it.)

### Step 4 — Terminal window 2: start the frontend

Open a **second** Git Bash window (leave the backend one running) and run:

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

The dev server proxies `/api/*` to the chat agent (`vite.config.ts`). The
voice widget calls the voice agent at `VITE_VOICE_API_BASE`
(`frontend/.env.example`), defaulting to `http://127.0.0.1:8002` if unset —
point it at the deployed voiceagent URL once that exists.

Open **http://localhost:5173** — both services are up, done.

### Or run each backend service individually

`run_all.sh` is a convenience, not a requirement — if you'd rather see each
service's own logs in its own window (or want to avoid the Git-Bash
process-management quirks noted above entirely), skip it and run each
`python main.py` from Step 2 directly, in its own terminal:

```bash
cd backend/chatagent && python main.py    # http://127.0.0.1:8001
```

```bash
cd backend/voiceagent && python main.py   # http://127.0.0.1:8002
```

That's back to 3 terminals total (2 backend + 1 frontend) instead of 2 —
exactly the tradeoff `run_all.sh` exists to avoid, but sometimes seeing
each service's output separately is worth it, e.g. when debugging one
service specifically.

To actually receive live voice calls, the Retell dashboard needs a **publicly
reachable URL** for `/webhook` and `/functions` — `http://127.0.0.1:8002`
only works for your own local testing. A tunnel (ngrok, cloudflared) is
fine for that, but it dies the moment your machine/tunnel stops running,
which isn't good enough for something meant to be reviewed asynchronously.
Deploy instead — see [Deployment](#deployment) below.

## Deployment

Retell needs a real, permanent URL for `/webhook` and `/functions` — it has
to work whenever a call happens, not just while your laptop is on. `render.yaml`
at the repo root is a [Render](https://render.com) Blueprint that deploys
both backend services with stable URLs:

1. Render dashboard → **New → Blueprint** → connect this GitHub repo.
2. Render reads `render.yaml` and proposes two services
   (`loveholidays-chatagent`, `loveholidays-voiceagent`). Fill in the env
   vars it prompts for (`GROQ_API_KEY`; `RETELL_API_KEY` + `RETELL_AGENT_ID`)
   — these aren't in the file itself, only their names are.
3. Deploy. Each service gets a URL like
   `https://loveholidays-voiceagent.onrender.com`.
4. In the **Retell dashboard**, on your agent:
   - **Webhook URL** → `<voiceagent-url>/webhook`
   - **Functions → + Add → Custom Function**, four times —
     `get_booking_details`, `get_luggage_options`, `add_luggage`,
     `escalate_to_human` — each pointing at `<voiceagent-url>/functions`
     (same URL for all four; a `name` field in the request tells the
     service which one to run). Parameter JSON schemas to paste in:
     `GET <voiceagent-url>/functions/schema` returns all four.
5. (Optional) If you want the browser voice-call button to hit the
   deployed voiceagent instead of localhost, set `VITE_VOICE_API_BASE` in
   the frontend's `.env` to `<voiceagent-url>`.

Free-tier Render web services spin down after inactivity and take a few
seconds to wake on the next request — fine for review, worth knowing if a
call seems to hang briefly on the first request.

## Testing

```bash
cd backend/chatagent   # or backend/voiceagent
pip install pytest
pytest ../../tests -v
```

Tests cover the pure booking-reference validation logic (no network calls) —
see [tests/](tests/) and the note in `EVALUATION.md` about what isn't covered
and why.

## API flow

1. Customer provides (or is asked for) a booking reference.
2. `get_booking_details` — soft-validates and normalizes the reference
   (trims, uppercases, extracts a plausible token from free text — no fixed
   format enforced), then calls the real API. The API is the source of
   truth for whether it exists.
3. If found and modifiable, `get_luggage_options` returns the available
   options. The real API prices luggage **per passenger**, so each option is
   scoped to one passenger; the assistant asks which passenger(s) if there's
   more than one.
4. Assistant confirms the exact option + price with the customer before
   calling `add_luggage`.
5. `escalate_to_human` fires on: booking not found 3 times in a row, booking
   not modifiable, no luggage options available, a tool call failing, or an
   explicit request for a human.

## Assumptions

- **`backend/data/sample_data.xlsx`** is the original synthetic dataset used
  to *design* the flow early on. Both agents now call the real hosted
  booking API directly — the spreadsheet isn't read at runtime and is kept
  only as a reference for the data shapes involved.
- **Booking reference format is intentionally not fixed.** Real formats vary
  (`LH123456`, `LOV2600001`, `ABC12345`, `LH-123456`); the assistant softly
  filters out obviously-invalid input (empty, too short/long, unsafe
  characters) and lets the API decide whether a reference is real, rather
  than gatekeeping on a guessed regex.
- **Session state is in-memory**, not persisted — the chat agent uses ADK's
  `InMemorySessionService`; the voice agent keys a plain dict by Retell's
  `call_id`. Both reset on process restart. Fine for this exercise; a real
  deployment would need shared state (Redis or similar) — see
  `PRODUCTION_CONSIDERATIONS.md`.
- **Groq's `llama-3.3-70b-versatile`** was chosen for chat for cost/speed.
  Groq has announced its deprecation (see the note at the top of
  `agent.py`) — swapping models is a one-line change (`MODEL` constant).

## Troubleshooting

- **`[WinError 10048] address already in use`** — a previous instance of that
  service is still running on the port; stop it or use a different port.
- **CORS error in the browser console** — the voice agent's CORS only
  accepts `localhost`/`127.0.0.1` origins (any port, via regex, since Vite
  picks a different port if 5173 is busy). If the frontend is served from
  somewhere else, add its origin in `voiceagent/main.py`.
- **Groq `tool_use_failed` / malformed function call** — an intermittent
  Llama-3.3-via-Groq issue where the model occasionally emits a
  pseudo-function-call as text instead of a structured tool call. `agent.py`
  sets `litellm.disable_aiohttp_transport = True` and an explicit
  `tool_choice="auto"`, which resolved it in testing, but it can still
  recur rarely — a retry (send the same message again) works around it.
- **`RETELL_API_KEY` gives `Invalid API Key`** — the value must come from
  Retell dashboard → **Settings → API Keys** (prefixed `key_`), not an
  agent ID or LLM ID.
- **Voice call never reaches `/webhook` or `/functions`** — Retell must be
  able to reach that URL over the public internet; `http://127.0.0.1:...`
  only works for `/create-web-call`, which the browser calls directly.

## Other docs

- [DESIGN_NOTES.md](DESIGN_NOTES.md) — key architectural decisions and why
- [EVALUATION.md](EVALUATION.md) — self-assessment against the exercise's goals
- [PRODUCTION_CONSIDERATIONS.md](PRODUCTION_CONSIDERATIONS.md) — what changes for real production use
- [EXAMPLE_CONVERSATIONS.md](EXAMPLE_CONVERSATIONS.md) — real transcripts from testing
