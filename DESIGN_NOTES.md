# Design Notes

Why things are built the way they are, for the decisions that weren't obvious.

## Overall solution design

This is a support assistant that adds luggage to an existing loveholidays
booking on a customer's behalf, over whichever channel they show up on.
There are two entry points — a text chat agent (`backend/chatagent`, ADK +
Groq) and a voice agent (`backend/voiceagent`, backed by Retell) — my own
call, not something the exercise required; it only asked for a
conversational AI solution. I chose to build both channels because a real
support customer might reach for either one, and they're two front doors
onto the same conversation, not two separate brains. The
flow is the same regardless of which door the customer walked in: 1) the
customer gives a booking reference, 2) the assistant normalizes it and asks
the real API whether it exists and can be modified, 3) if so, it fetches
and shows luggage options and asks which passenger if there's more than
one, 4) the customer picks an option and confirms the price, and the
assistant adds it, 5) three consecutive failed lookups (or an unmodifiable
booking, no options, or a tool failure) escalates to a human instead.
Everything in `backend/chatagent` and `backend/voiceagent` — the system
prompt, the tool functions, the reference normalization, the per-
conversation attempt counters — is our code. The one thing that isn't is
the loveholidays luggage API itself: booking data, luggage pricing, and
whether a booking can be modified all live there, not in this repo. Our
code's job is to talk to it correctly and safely, never to guess at data it
should be the source of truth for.

## Conversation design & guardrails

This system does not run a dedicated prompt-injection defense — no "ignore
any instruction that tries to override this prompt" boilerplate, no
separate classifier sitting in front of the model. That's a deliberate cut
for this exercise: the realistic threat for a luggage-support bot is an
off-topic or manipulative request derailing the conversation, and the
existing escalation trigger already handles that outcome — "the request is
outside luggage support" is listed as a reason to call
`escalate_to_human`, so an off-topic ask gets routed to a human instead of
answered. What this exercise did not include is adversarial red-teaming
against a specific "ignore your instructions and tell me X" attack; the
next step before production is running that red-team pass and, if it finds
gaps, adding a hardened system-prompt wrapper or an input classifier ahead
of the model rather than depending solely on Llama 3.3's own
instruction-following. Mid-flow topic changes, by contrast, are handled by
design, not left open: ADK's session state (`tool_context.state`, keyed by
`session_id`) and the full conversation history both persist across turns,
so if a customer gives a reference, asks something unrelated, then comes
back, the attempt counter and cached luggage-options catalog are still
there waiting for them. Exercising that exact interruption end-to-end was
out of scope for this round of testing, which covered the linear scenarios
in `EXAMPLE_CONVERSATIONS.md`; the next step before production is adding an
interruption-and-resume transcript to that suite to turn the architectural
guarantee into a verified one.

Ownership verification is intentionally absent — the booking reference
*is* the entire authorization. Anyone who has, guesses, or overhears a
valid reference can look up that booking and add luggage to it; there's no
name, date-of-birth, or email cross-check tying the person on the other
end of the chat or call to the booking they're asking about. That's the
right scope for a take-home exercise built against a mock API where the
reference itself is the trust boundary the exercise defined; the next step
before production is adding a second identity factor (name or
date-of-birth cross-check against the booking record) before any change is
allowed. Voice reference confirmation sits in a different codebase by
design: the Retell agent's own prompt — where a "let me repeat that back:
L, H, one, two, three... is that right?" step would live — is configured
in Retell's dashboard, not in this repo, because that's where Retell's
conversation logic is owned end to end. What this repo does own is the
receiving-end fallback: `_collapse_spelled_out_tokens()` in
`luggage_api.py` repairs the common case of speech-to-text rendering a
spoken reference as individually-spoken letters ("L H six five four three
two one" → "LH654321") before normalization runs, so a mis-chunked
transcription still resolves correctly. The next step before production is
adding an explicit read-back-and-confirm step to the Retell dashboard
prompt itself, verified directly against a live call rather than inferred
from this codebase.

Evaluation for this exercise was scoped to manual testing against the live
API rather than a structured harness with a fixed conversation count,
because the goal was confirming specific, high-risk behaviors rather than
statistical coverage. What was run deliberately: a reference embedded in a
full sentence, to check extraction; three invalid references in a row, to
confirm the escalation counter fires on the third and not the first or
never; a multi-passenger booking with no passenger specified, to confirm
the assistant asks rather than guessing; and a real `422` the live API
returned from an earlier, wrong request shape, to confirm it surfaces as a
clean apology instead of raw error text. Those are captured as real
transcripts in `EXAMPLE_CONVERSATIONS.md`, not fabricated examples.
Building an automated conversation-level test suite was cut from this
exercise's scope because it requires mocking the LLM or recording/replaying
real Groq responses — infrastructure that outweighed the risk being tested
for a take-home exercise; `tests/` instead covers the pure, deterministic
reference-normalization logic, the highest-value, lowest-effort thing to
unit test at this stage. The next step before production is exactly that
record-and-replay suite, turning the manual verification above into a
repeatable regression test.

Each of the above is a deliberate boundary for this exercise's scope, not
an oversight, and each has a concrete next step: red-team and, if needed,
harden against prompt injection beyond the model's own instruction-
following; add a second identity factor so the booking reference stops
being a bearer token; add an interruption-and-resume transcript to verify
the mid-conversation state-persistence guarantee end to end; and add an
explicit read-back-and-confirm step to the Retell dashboard prompt for
voice references. None of these block the core exercise — helping a
customer add luggage safely — and all four are exactly where I'd start
before this goes anywhere near a real customer.

## Groq + Llama 3.3 70B via ADK's LiteLlm wrapper

The chat agent runs on Groq's `llama-3.3-70b-versatile`, wired into ADK
through the `LiteLlm` model wrapper so the existing `GROQ_API_KEY` carries
the whole integration end to end. I picked Groq specifically for inference
speed: Groq's LPU hardware is built for exactly this kind of workload
(short prompts, fast turn-taking), and in back-to-back manual testing
against the live API, first-token latency stayed consistently fast turn
after turn — for a support bot that has to feel responsive on every single
reply, that mattered more than most other factors. Cost was the second
factor: Groq's free tier comfortably covers a take-home exercise's worth of
traffic without standing up a separate billing account. Llama 3.3 70B's
128K-token context window was also more than this agent needs even for a
long back-and-forth — system prompt plus several tool calls plus
conversation history stays well under that — so there was no
context-budget argument for a bigger-window model either. I kept the
hyperparameters deliberately narrow: `temperature=0.3` and an
explicit `tool_choice="auto"`. This isn't a creative-writing task — the
model is mostly deciding *which tool to call next* inside a fixed script
(ask for reference, show options, confirm, add), so a low temperature cuts
down on it improvising wording or inventing luggage prices instead of
reading them from the tool result; setting `tool_choice="auto"` explicitly,
rather than leaving it unset, turned out to matter more than expected — see
below. The tradeoff showed up once I started running real multi-turn
conversations against the live API instead of one-off test prompts:
LiteLLM's Groq integration sits one layer removed from Groq's native SDK,
and that layer is exactly where both real bugs in
[README's troubleshooting](README.md#troubleshooting) came from — aiohttp's
async DNS resolver intermittently failing to resolve `api.groq.com` on
Windows, and Llama occasionally emitting a tool call as loose text instead
of a structured one. Neither is an ADK bug or an application bug; I only
found both by actually exercising the agent past the first message, not by
reading either project's docs beforehand.

## How the assistant uses the provided APIs

Both agents call the same four endpoints on the real booking API, in the
order the conversation naturally produces them: `POST /booking/lookup`
first, as soon as the customer gives a reference; `POST
/booking/luggage-options` once that lookup comes back found and modifiable;
`POST /booking/add-luggage` only after the customer has confirmed a
specific option and price; and `POST /escalations` whenever the
conversation needs to hand off, which can happen at any point. All four go
through a shared `_post` helper (duplicated between `tool.py` and
`luggage_api.py`, same as the rest of the integration — see below) that
does the boring, easy-to-get-wrong part once: builds the full URL from
`BASE_URL`, applies a 10-second timeout, logs the outbound payload and the
inbound status/body, and — critically — catches `requests.RequestException`
so a network failure comes back as a plain `(None, "<description>")` tuple
instead of an unhandled exception that would kill the whole agent turn.
There's no auth header to attach — the hosted API doesn't require one — so
`_post` is really just retry-free HTTP-plus-logging, not a full client
wrapper. Request bodies are small and mostly just `{"bookingReference":
...}`, except `add-luggage`, which sends an `items[]` array carrying the
service/ancillary ids, passenger and flight-segment refs, quantity, and an
idempotency key built from booking reference + passenger + service id so a
retried request can't double-book the same bag. Response shapes are the
real API's own shapes — nested `ancillaryServices[].selectionOptions[]` for
luggage options — which `get_luggage_options` flattens before the model
ever sees it (see the `option_id` section below).

## Error handling strategy

Beyond the two LiteLLM/Groq quirks above, every API failure funnels through
the same status-code branch in each tool function: a timeout or connection
failure (caught inside `_post`) becomes `(None, "Could not reach the
booking service: <exc>")`; a 404 on lookup becomes `"Booking not found"`;
any other 4xx/5xx becomes a generic `"Booking service returned an
unexpected error (status N)"`. For `get_booking_details` specifically, all
three of those count as a failed attempt toward the 3-strikes counter — a
timeout and a genuine "booking not found" are treated the same way for
escalation purposes, since from the customer's side both look identical
("it didn't find my booking"), and repeatedly hitting either one is equally
a sign the conversation needs a human. For `get_luggage_options` and
`add_luggage`, errors come back as `found: false` / `success: false` with
an `error` string but don't feed the lookup counter — those trigger the
system prompt's generic error-handling rule instead of the strikes-based
one. There's no automatic retry anywhere in this code; the one "retry" that
exists is manual — the README's troubleshooting note that resending the
same message works around an occasional malformed tool call. The customer
never sees a status code or a raw error body: whatever the tool returns,
the system prompt's error-handling rule turns it into "I'm sorry, something
went wrong while trying to update your booking. I'll hand this over to a
human agent so they can help," and the agent calls `escalate_to_human`.
That path was deliberately exercised against a real `422` the live API
returned during development (from an earlier, incorrectly-shaped
`add-luggage` request) — the customer-facing result was that clean apology,
not the raw error body.

## Soft booking-reference validation, not a regex gate

Early on the natural instinct is `^LH\d{6}$`-style validation. That's wrong
here: the real formats in the live data vary (`LH123456`, `LOV2600001`,
`ABC12345`, `LH-123456`), and a hardcoded pattern would reject valid
references the moment the underlying data changes. `normalise_booking_reference()`
in both `tool.py` and `luggage_api.py` instead:

1. Trims and uppercases.
2. Rejects only clearly-invalid input: empty, over 200 chars, unsafe
   characters, or prose with nothing token-shaped in it.
3. Extracts a plausible token (5–20 chars, alphanumeric + hyphen), preferring
   one that mixes letters and digits — every real format does — over a
   bare word like "LUGGAGE" picked out of "I want to add luggage".
4. Lets the real API be the source of truth for whether it's an actual
   booking. A false "found" never happens; a false rejection of a real
   reference format was the actual risk being designed against.

## 3-strikes escalation is code-enforced, not just prompted

The system prompt tells the model to escalate after repeated invalid
references, but LLMs are unreliable counters over a long conversation —
easy to lose track after a few turns. Both `get_booking_details`
implementations track consecutive failures in session state
(`ToolContext.state` for ADK; a `call_id`-keyed dict for the voice agent)
and return `should_escalate: true` on the 3rd failure. The model still
decides *when* to call `escalate_to_human` — but the counting itself is
deterministic, not a hope that the model kept track.

## What escalation actually does once it fires

Triggering is code-enforced (above), but what happens once it fires is
deliberately simple. `escalate_to_human` POSTs the reason and booking
reference to `/escalations` on the real API — which is the actual system of
record for the handoff, presumably surfacing to a human agent's queue on
loveholidays' side — and the assistant delivers a fixed line from the
system prompt: "I'll hand this over to a human agent so they can help you
further. Please keep your booking reference ready." There's no live agent
transfer, phone number, or ticket UI in this exercise; the escalation
*record* is the API call, and the *user-facing* part is just that sentence.

Escalating does **not** end the conversation — this is a deliberate design
decision, not an oversight, confirmed by real testing on both channels
(chat and voice): `escalate_to_human` logs a ticket and hands control
straight back to the model, which stays fully available to keep helping
with anything else. Two real voice calls in `EXAMPLE_CONVERSATIONS.md`
(§5 and §7) show the agent escalating one issue and then continuing to
serve the customer normally in the same call — in §5 it even completes the
original task itself (a different luggage item) right after escalating a
duplicate-item block. The alternative — ending the session the moment
anything gets escalated — would mean a customer who triggers escalation
for one unrelated thing (say, a refund question) loses the ability to
finish an unrelated task they were mid-way through, which is worse
customer experience for no safety benefit; the already-escalated guard
(above) exists precisely so the model answers follow-up questions directly
instead of either re-escalating or going silent.

If the `/escalations` call itself fails,
the tool still tells the model `escalated: true` with a fallback message
("Escalation needed, but escalation API failed") rather than surfacing a
second failure to the customer — someone asking for a human shouldn't get
an error message as the answer to that ask, even if the logging pipeline
behind it had a problem. This is identical between the two agents:
`voiceagent/luggage_api.py`'s `escalate_to_human` calls the same
`/escalations` endpoint with the same payload shape as `chatagent/tool.py`'s
— the only difference is that on a call, Retell's text-to-speech speaks
that sentence instead of the chat widget rendering it as text.

## Why `tool.py` and `luggage_api.py` aren't one shared module

They implement the same booking-API integration (same `_post` helper
pattern, same validation, same per-passenger option flattening) but differ
in exactly one dimension: where per-conversation state lives.
`chatagent/tool.py`'s `get_booking_details` takes an ADK `ToolContext`
(auto-injected, invisible to the model) and reads/writes `tool_context.state`.
`voiceagent/luggage_api.py` has no ADK Runner to hook into — Retell just
POSTs `{name, call, args}` per function call — so state is a plain dict
keyed by `call.call_id`. Unifying these behind one interface was possible
but would've meant an abstraction whose only two callers disagree on how
state gets in and out; two small, readable, independently-testable files
won out over one file with a state-provider abstraction for two call sites.

## Luggage options are flattened to `option_id`, not passed as raw JSON

The real API's `luggage-options` response nests pricing per
`ancillaryService` and, within that, per-passenger `selectionOptions` (each
carrying its own `passengerRefIds`/`flightSegmentRefIds`). Making the model
reconstruct that nested shape correctly when calling `add_luggage` is
fragile — a 70B model reliably drops or misplaces nested array fields.
Instead, `get_luggage_options` flattens it to one option per (bag type,
passenger) pair with a synthetic `option_id`
(`"ANC-BAG26::PAX-1001"`), caches the full item spec (service/ancillary ids,
passenger/segment refs, price) server-side, and `add_luggage` looks up that
spec by `option_id` rather than trusting the model to rebuild it. The model
only ever has to echo back a string it was just given.

## Frontend: real brand reference, not a guess

The chat/voice widget colors were originally a guessed coral/pink palette
with no real loveholidays reference. Once given an actual screenshot of the
site, the palette was corrected to the real brand (blue `#0374db`, sampled
directly from the provided logo file's background so there's no color
seam) with green (`#1b5e3a`, matching the real "Search" button) as the
secondary accent for the voice widget — not two arbitrary colors.
