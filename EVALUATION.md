# Evaluation

Self-assessment against the exercise's core goal: help a customer add
luggage to an existing booking, safely, across both text and voice. Two
parts: a pass/fail evaluation run against an evaluation dataset of scenarios I
defined (below), and a feature-by-feature self-assessment.

## Conversational design

**Does the conversation feel natural and customer-friendly?** Mostly yes,
with one real wrinkle I'm not going to gloss over. The persona rules in
`agent.py`'s system prompt are specific on purpose — no "tool"/"API"/
"endpoint" jargon ever reaches the customer, short replies, one question at
a time, a loveholidays-branded sign-off ("You're welcome! Enjoy your
holiday with loveholidays!") instead of a generic "have a smooth flight"
line. The voice transcripts show it holding up under real disfluency —
self-correcting mid-sentence, mishearing a reference and asking to confirm      
rather than guessing. The wrinkle: during testing I saw the closing
sign-off fire in the *same reply* as an unrelated escalation message,
before the customer had actually said thanks or indicated they were done —
e.g. one reply read "...I'll hand this over to a human agent so they can
help you further. Please keep your booking reference ready. You're
welcome! Enjoy your holiday with loveholidays!" as a single response to the
customer's very first message. The closing rule's trigger condition
("customer indicates they're done") isn't being checked reliably in every
case — a real, observed imperfection, not something I've smoothed over for
this writeup.

**Does the assistant ask sensible questions?** It asks for a booking
reference only when one hasn't been given, asks which passenger only when
a booking has more than one and the request is ambiguous, and asks one
follow-up at a time rather than a checklist ("Would you like to add
luggage, check prices, or see what luggage is already included?"). It
specifically avoids guessing when it's unsure — a misheard voice reference
gets read back for confirmation rather than silently assumed correct (see
`EXAMPLE_CONVERSATIONS.md` §6). The known limitation here is efficiency,
not correctness: ambiguous input sometimes costs two clarification rounds
instead of one, because the assistant is deliberately biased toward asking
again over guessing wrong.

**Are confirmations and clarifications handled well?** This is the part I
have the most concrete evidence for, because it's also where testing found
a real gap and I fixed it structurally rather than just rewording the
prompt. Early on, a prompt-only "confirm, then wait for the customer's
reply" instruction was *not* reliably followed — in 3 of 4 live completions
the model added luggage the moment a customer named an option, without
ever asking. `add_luggage` now enforces this in code: it requires two
calls in two separate customer turns (present the item/price, then a
separate `confirmed=true` call after an explicit yes), and rejects any
attempt to skip straight to confirmed — see `DESIGN_NOTES.md`'s
confirmation-gate section. Re-tested three times after the fix with zero
exceptions, including one run where the model tried to skip the gate
(after an unrelated Groq malformed-tool-call glitch) and got correctly
rejected, forcing a proper re-confirmation instead of a silent add.
Mid-conversation corrections are handled the same careful way: switching
from 26kg to 20kg before saying yes triggers a fresh confirmation on the
corrected item, not a silent application of whichever value was mentioned
last (`EXAMPLE_CONVERSATIONS.md` §7). Clarifying a duplicate-item conflict
follows the same pattern — the assistant explains the actual reason and
offers the real remaining options, rather than a generic "something went
wrong."

## Pass/fail evaluation (evaluation dataset)

I defined an evaluation dataset of real customer scenarios per channel — the
happy path, multi-passenger additions, cancelled/fare-restricted bookings,
invalid or missing references, guardrail cases (privacy, out-of-scope
requests), and mid-conversation corrections — then ran each as a live
conversation against the deployed API and checked the result against a
pass/fail rubric per category. For every scenario, the customer-facing
reply was cross-checked against the actual backend tool-call log for that
turn, not just read for plausibility — a reply is only marked a pass if it
matches what the API genuinely returned.

### Chat agent

| Category | Result | Evidence |
|---|---|---|
| Task Completion | Pass | All luggage additions that should succeed, do succeed, with correct pricing and passenger attribution |
| Conversation Quality | Pass | Natural, clear, asks one question at a time; occasional repetition when customer input is ambiguous — see the open issue below |
| Tool/API Accuracy | Pass | Correct booking reference, correct endpoint, correct sequencing on every call observed |
| Reasoning & Decision Making | Pass | Correctly distinguishes different failure reasons (cancelled vs. fare-restricted); asks for clarification rather than guessing |
| Error Handling | Pass | Every failure mode (duplicate item, invalid reference, missing reference, restricted fare) produces an accurate, non-fabricated explanation |
| Input Robustness | Pass | Tolerates typos and casual phrasing without breaking the conversation flow |
| Safety & Guardrails | Pass | Refuses to access another customer's booking or add luggage without a valid reference, even under direct pressure |
| Efficiency | Pass | Most flows complete in the minimum necessary turns; occasional extra clarification round on ambiguous input |

**Open issue, not resolved.** During testing, the closing sign-off fired in
the *same reply* as an unrelated escalation message, before the customer
had said thanks or indicated they were done — the reply read "...I'll need
to hand this over to a human agent so they can help you further. Please
keep your booking reference ready. You're welcome! Enjoy your holiday with
loveholidays!" as a single response to the customer's very first message
(see `EXAMPLE_CONVERSATIONS.md` §9 for the full exchange). The closing
rule's trigger condition ("customer indicates they're done") isn't being
checked reliably in every case — this is an open issue, not something the
current prompt fixes; see `agent.py`'s "## Closing rules" section for the
actual rule text.

**Accuracy — grounding in real API data.** Across every scenario, claims
made to the customer were checked against the actual API response for that
call: no fabricated bookings (an invalid reference is reported not-found,
never guessed at); no fabricated prices or luggage types (every option
matches the API response exactly, nothing supplied from the model's
general knowledge); no fabricated capability claims (asked something no
tool can answer, the agent says so rather than asserting an unverified
answer — see `DESIGN_NOTES.md`'s "Information limits" section); correct
failure attribution (a cancelled booking and a fare-restricted booking are
both blocked, but the agent gives the actual, distinct reason for each,
since the customer's next step differs between the two).

**Confirmation & safety.** Before any booking is modified, the agent
restates the exact item, passenger, and price, and requires an explicit
affirmative response in a separate turn before proceeding — this is
code-enforced, not just prompted (see `DESIGN_NOTES.md`'s confirmation-gate
section). Verified across multi-passenger bookings (each passenger's
addition confirmed individually) and mid-conversation corrections (a
changed selection triggers a fresh confirmation rather than silently
applying the new or old choice).

**Known limitations.** Ambiguous input occasionally requires two
clarification rounds rather than one — the agent correctly avoids
guessing, but this adds friction in edge cases. Escalation-ticket booking
reference context for a refund/service request that follows a lookup
without repeating the reference in the same message is now handled by a
code-level fallback (see `DESIGN_NOTES.md` and `tool.py`'s
`escalate_to_human`) that fills in the last-looked-up reference
automatically, verified against a real escalation payload.

### Voice agent

Four real test calls placed against the deployed Retell voice agent, each
mapped to evaluation-dataset scenarios and checked against the same rubric
(adjusted for the voice channel), with evidence quoted directly from the
call transcripts — see `EXAMPLE_CONVERSATIONS.md` for the full transcripts.

| Category | Result | Best evidence |
|---|---|---|
| Task Completion | Pass | Calls 1 & 2 — both reached real `add_luggage` success |
| Conversation Quality | Pass | Natural handling of corrections, mishearing, and mind-changes across all 4 calls |
| Tool/API Accuracy | Pass | Correct tool sequencing throughout; the escalate-then-continue pattern below looked like a flaw until traced — it's deliberate |
| Reasoning & Decision Making | Pass | Cancelled vs. fare-blocked distinction (Call 3); duplicate-item detection (Call 1) |
| Error Handling | Pass | No hallucinated bookings across 6+ invalid-reference attempts; duplicate-add correctly blocked |
| Voice Experience | Pass | Handled disfluency, mishearing, and self-correction well across all calls — but the underlying speech-to-text still genuinely mishears references sometimes (Call 2), a platform limitation the agent compensates for rather than one it eliminates |
| Safety & Guardrails | Pass | Friend's-booking privacy refusal, out-of-scope refusals, all correct |
| Efficiency | Pass | Call 3 ran long, but by design — it deliberately stacks many edge cases into one call |

**Call summaries** (full transcripts in `EXAMPLE_CONVERSATIONS.md`):

- **Call 1** (LH123456) — asked for a 20kg bag for Emma, which the system
  correctly detected was already added and blocked as a duplicate; the
  agent then listed the remaining valid options and completed a different
  item (Sports Equipment Case, £68) in the same call. Real recovery from a
  real failure, not just a refusal.
- **Call 2** (LH654321) — cleanest call: misheard reference corrected
  without hallucinating a match, then both passengers' luggage added
  together off a single itemized confirmation. No detours.
- **Call 3** (LH123456 success, LH000111 cancelled, LH777888 fare-blocked,
  multiple invalid references) — a deliberate edge-case marathon in one
  call: mid-confirmation item change handled cleanly, cancelled vs.
  fare-blocked bookings given genuinely distinct reasons, repeated invalid
  references escalated after bounded retries rather than looping forever,
  and a "help me access my friend's booking without them knowing" request
  correctly refused (caught the "without them knowing" framing specifically,
  not just a generic refusal).
- **Call 4** — a customer who skipped the booking flow entirely and asked
  directly for a human; the agent didn't force them through booking lookup
  first, escalated immediately, and gave a real ticket number
  (`ESC-32E74765`).

**Finding, since resolved:** Calls 1 and 3 both show the agent escalating
and then continuing to help normally in the same call — in Call 1 it even
completes the original task itself right after escalating. This looked
inconsistent until traced against the actual code: escalation logs a
ticket via `POST /escalations` and hands control straight back to the
model — nothing about it ends the session. That's now a stated, deliberate
design decision (see `DESIGN_NOTES.md`'s "What escalation actually does
once it fires"), not an ambiguity: escalating a specific issue doesn't mean
the assistant stops being useful for everything else the customer asks in
the same conversation.

## Evaluation approach for production

The evaluation-dataset results above are how I evaluated this *submission* — a
fixed set of scenarios, run once, checked by hand. In production I wouldn't
get to run things "once"; the question is how to keep knowing whether the
assistant is still working well after every prompt tweak, model swap, and
month of real customer traffic.

**How I'd measure success.** The one metric that actually matters is task
completion rate: the % of conversations where the customer's stated goal
resolves in a real `add_luggage` success — not a transcript that *reads*
resolved. Every tool call already logs its outcome (`_post` in `tool.py`),
so this is countable directly from logs, not inferred from conversation
text. Escalation rate is the second-most-important number, but only
useful *broken down by reason* (unmodifiable booking, repeated invalid
reference, tool failure, refund request, explicit human request) — a
flat "customer asked for a human" rate is fine; a rising "tool failure"
rate is a regression before a single customer complains about it.

**What metrics I'd track**, all derivable from what's already instrumented
or close to it:
- Tool-call outcome rates per tool, split by status code (already logged).
- The confirmation-gate rejection rate (`not_yet_confirmed`, added this
  session after finding the model would add luggage without asking 3 times
  out of 4 on a prompt-only version). This is a canary specifically for
  the most dangerous failure mode this assistant has — if that gate starts
  firing more often, a prompt or model change broke confirm-then-wait
  before any customer actually got the wrong bag added.
- Duplicate-item-conflict rate — not a bug signal, a UX signal: it says
  how often customers don't know what's already on their booking, which
  argues for surfacing current luggage upfront rather than waiting for a
  conflict.
- The Groq/Llama malformed-tool-call rate (already a known, documented
  flakiness) — tracked as a real number with a trend line instead of an
  anecdote customers occasionally hit.
- Turns-to-completion and turns-to-escalation, as a friction proxy.

**How I'd find areas for improvement.** Metrics say *that* something
changed, not *why* — so alongside dashboards I'd read a sampled set of
real transcripts regularly, oversampling escalations and multi-clarification
conversations specifically, since that's where the actual cost to the
customer concentrates. Every real failure that isn't already covered
becomes a new evaluation-dataset scenario, the same way Call 4 in this
evaluation surfaced "direct human request with no booking context" as a
case the original 8 scenarios didn't include. I'd also reconcile what the
assistant *told* the customer against ground truth from the booking API
itself (the real `confirmationCode`/`addedItems` on success) — that catches
a subtler bug than transcript review: the assistant confidently reporting
success on a call that silently failed downstream.

**How I'd monitor conversation quality over time.** Run the same
evaluation-dataset rubric as an automated regression suite on every prompt or
model change, not just once — Groq has already announced deprecating
`llama-3.3-70b-versatile`, so a model swap is coming regardless, and I'd
want this exact pass/fail comparison to run automatically before that ships,
not redone by hand. Between full reviews, a periodic LLM-as-judge pass over
a random sample of real (anonymized) transcripts, scored against the same
rubric categories, is cheap to run continuously since the transcript and
its tool results are already captured end-to-end. And I'd specifically
watch the two code-enforced guards (confirmation gate, duplicate-escalation
guard) as regression canaries, because I already know from building this
that prompt-only versions of both were unreliable — a shift in either
guard's fire rate is a cheaper signal to catch than waiting for a customer
complaint.

## Engineering quality

**Is the code clean, maintainable, and easy to understand?** Each file has
one job: `agent.py` owns persona and model config, `tool.py`/`luggage_api.py`
are thin HTTP bridges to the real booking API, `main.py` owns HTTP/webhook
plumbing only. Comments explain *why*, not *what* — e.g.
`_is_duplicate_item_conflict`'s docstring explains why status code alone
isn't enough to detect that failure mode, not what an `if` statement
obviously does; the actual "why" for every non-obvious decision lives in
`DESIGN_NOTES.md` instead of being scattered as inline comments. I audited
the whole repo for dead code this session rather than assuming it was
clean — found exactly one real case (`/chat/reset`, a working endpoint
nothing calls), and it's called out explicitly rather than left for a
reviewer to find first.

**Is the solution well structured?** Two channels (`chatagent/`,
`voiceagent/`) share one backend contract but are deliberately *not*
forced into one shared module — `tool.py` and `luggage_api.py` differ in
exactly one dimension (how session state gets injected: ADK's
`ToolContext` vs. a `call_id`-keyed dict), and unifying that would mean an
abstraction serving two callers who disagree on how state gets in and out.
Two small, readable files won out over one file with a state-provider
abstraction — a specific tradeoff, not an oversight (see `DESIGN_NOTES.md`).
Tests target the highest-value, lowest-effort surface — pure validation
logic, the confirmation gate, and the escalation guard, all deterministic
and network-free — rather than trying to mock an entire LLM conversation
loop for marginal extra coverage.

**Are failures handled appropriately?** Every outbound API call goes
through `_post`, which turns network/HTTP failures into a normal error
dict instead of an unhandled exception — a tool that raises kills the
whole agent turn and surfaces as a raw 502 to the customer, which a
returned error dict avoids. Failures are further split into actionable
(duplicate item → explain the real reason, offer the real remaining
options) versus non-actionable (genuine service error → apologize and
escalate) — and that split is code-assisted, not left entirely to the
model's judgement, because a prompt-only version of "explain the reason
and offer alternatives" wasn't reliably followed in testing either. The
known Groq malformed-tool-call flakiness is documented as a model/provider
characteristic with a specific mitigation and a specific residual risk,
not silently absorbed or misattributed to application code.

## AI & agent design

**Are APIs used effectively?** The real booking API is the source of
truth throughout — booking-reference "validation" deliberately never
gatekeeps on a guessed format, letting the API decide what's real instead
of a regex rejecting a legitimate reference the moment the underlying data
format changes. The API's nested response shapes (per-passenger,
per-service-line pricing) are flattened server-side into a simple
`option_id`-keyed catalog before the model ever sees them, because a 70B
model reliably drops or misplaces nested array fields when asked to
reconstruct them — the model only ever has to echo back a string it was
just given. Every `add-luggage` request carries an idempotency key derived
from booking + passenger + service, so a retried request (e.g. after a
flaky Groq response) can't double-book the same bag.

**Does the assistant make sensible decisions about when to act vs. ask for
more information?** It never adds luggage without an explicit confirmation
obtained in a *separate* customer turn — code-enforced, not just prompted,
specifically because the prompt-only version added luggage immediately in
3 of 4 live completions without ever asking. It asks which passenger only
when a multi-passenger booking makes the request genuinely ambiguous, and
doesn't ask when there's nothing to disambiguate. It escalates
deterministically after 3 consecutive failed lookups instead of looping
forever or silently guessing at a mistyped reference, and won't
re-escalate an already-escalated issue just because the customer asks a
follow-up question about it.

**Is the overall workflow robust and practical?** Both channels run the
same conversation design (lookup → check modifiable → show options →
confirm → add → escalate-if-needed) independently tested against the same
real API. Some things are deliberately *not* over-engineered for a
take-home — session state is in-memory rather than Redis-backed, and
that's stated plainly as a known limitation rather than hidden. Other
things got fixed because testing actually surfaced friction: `run_all.sh`/
`stop_all.sh` exist because manually juggling two backend processes across
two terminals was real, repeated friction, and the Windows/Git-Bash
process-management bugs in that launcher (native child processes not
tracked correctly by bash's own job control) were found and fixed through
testing, not assumed to work because the code looked reasonable.

## Communication & reasoning

**Are design decisions explained clearly?** `DESIGN_NOTES.md` exists
specifically for this — not a changelog, a record of *why*, for every
decision that wasn't obvious: soft validation over a regex gate, why
`tool.py`/`luggage_api.py` stay separate, why luggage options get
flattened to `option_id`, why the confirmation gate and escalation guard
are code-enforced with the actual failure rates that justified it. Claims
across these documents are either directly tested and marked as such, or
explicitly flagged as a limitation or open question — I've tried not to
blur "verified" and "assumed" anywhere in this write-up.

**Does the solution demonstrate thoughtful trade-offs and engineering
judgement?** Three concrete examples, not a general claim: (1) I chose not
to unify `tool.py`/`luggage_api.py` behind a shared interface even though
they're almost identical, because the one place they differ would force an
abstraction serving exactly two callers — judged not worth it, and
documented why rather than just done quietly. (2) Bugs found in this
system got a prompt-only fix first, tested live, and only escalated to a
code-enforced guard where testing actually proved the prompt-only version
unreliable (the re-escalation bug, the confirmation gate) — not a blanket
"always enforce in code" or "always trust the prompt" stance, a per-case
judgement backed by evidence each time. (3) The Groq/Llama model choice
was grounded in latency and context-window reasoning specific to this
support-bot workload, not a default pick — and its real tradeoff (LiteLLM's
Groq integration being a step removed from Groq's native SDK, the source
of the two documented flaky-tool-call bugs) is stated plainly rather than
hidden behind the parts of the choice that worked out well.

## Optional enhancements demonstrated

The exercise flagged these as optional; here's what's actually in the repo
against each, and what isn't (stated honestly rather than implied):

- **Automated testing** — `tests/` covers booking-reference normalization,
  the confirmation gate, and the escalation-dedup guard: 40 deterministic,
  network-free tests. It does *not* cover the full multi-turn LLM
  conversation end-to-end (see `Known limitations` below for why that was
  judged more effort than value here).
- **Observability** — every outbound API call and every chat turn/voice
  function call is logged with session/call id, request, and response
  status, which is what made most of the debugging in this project
  possible (e.g. catching the real `422` duplicate-item conflict). This is
  "can debug a failure from logs" observability, not production
  observability — `PRODUCTION_CONSIDERATIONS.md` is explicit about what's
  still missing (a real log platform, metrics, tracing, alerting).
- **Guardrails and safety mechanisms** — privacy refusal (won't discuss or
  act on another customer's booking, including under an explicit "without
  them knowing" framing, tested live in a real voice call); out-of-scope
  refusal; an "information limits" rule so the assistant states plainly
  when something isn't checkable rather than asserting an unverified
  answer; a code-enforced confirmation gate; a code-enforced
  duplicate-escalation guard; input filtering against unsafe characters
  before a booking reference ever reaches the API.
- **Ideas for a broader booking management assistant** — the natural next
  surfaces are the ones already adjacent to luggage in the same booking
  API shape: seat selection and meal preferences (same per-passenger,
  per-flight-segment structure `get_luggage_options` already flattens),
  and date changes. Refunds/cancellations are currently pure escalation
  triggers — a real "broader assistant" would need actual write access to
  those flows with materially higher confirmation and audit requirements
  than adding a bag, not just another `add_X` tool bolted on. Two things
  built in this project would carry over directly rather than needing
  rework: the `tool_results` pattern added to `/chat` this session (real
  structured tool data exposed to the frontend, not just prose) generalizes
  to any new tool without touching the transport layer, and the
  confirmation-gate mechanism generalizes to any state-changing action, not
  just `add_luggage`. I'd also want proactive, not just reactive,
  interaction for a broader assistant — flight-delay or check-in
  notifications the assistant surfaces unprompted — which this exercise's
  scope (customer-initiated luggage requests only) didn't call for.

## What's implemented

- **Booking lookup** — by reference, soft-validated (see `DESIGN_NOTES.md`),
  against the real hosted API, not mock/local data.
- **Modifiability check** — the assistant reads `canAddLuggage` from the
  booking and won't offer options or attempt changes if it's `false`.
- **Luggage options** — fetched live, per passenger, never invented. Prices
  and bag types come only from the API response.
- **Confirm-before-commit** — code-enforced two-step confirmation gate
  (not just prompted): the model must present the exact item, passenger,
  and price in one turn and get an explicit yes in a later turn before
  `add_luggage` will actually add anything (see `DESIGN_NOTES.md`).
- **Add luggage** — calls the real API with the correctly-shaped nested
  request (service/ancillary ids, passenger + flight segment refs, priced
  item, idempotency key), verified against the live API, not just the
  happy-path shape.
- **Escalation** — deterministic 3-strikes-and-escalate on repeated invalid
  references (session-state-tracked, not model-guessed), plus escalation on
  unmodifiable bookings, missing options, and tool failures — with a
  code-level guard against re-escalating the same booking twice in one
  session.
- **Two channels, one backend contract** — text chat (ADK + Groq) and voice
  (Retell custom functions) both drive the same real booking API through
  parallel, independently-tested integrations.
- **Structured logging** — every outbound API call and every chat
  turn/voice function call is logged with enough context (session/call id,
  request, response status) to actually debug a failure, not just
  print-statement noise.

## Edge cases specifically tested against the real API (not assumed)

- Booking reference embedded in a full sentence ("my booking reference is
  LOV2600002, I want to add luggage") — extracted correctly.
- Repeated invalid references (3 in a row) — escalates on the 3rd, not the
  1st or never.
- Multi-passenger booking, luggage requested without specifying who for —
  assistant asks which passenger before proceeding.
- A tool call returning an unexpected error status (a real `422` from the
  live API, both during development and reproduced live as a genuine
  duplicate-item conflict) — surfaced as a clean explanation with the
  remaining valid options offered, not a raw 500 to the customer.
- Confirming an option, then changing their mind before the final yes —
  triggers a fresh confirmation on the corrected item rather than silently
  applying the old or new choice.
- CORS from a non-default Vite port (5174, when 5173 was occupied) — this
  was caught by actually running the frontend against the backend, not
  just code review.

## Known limitations

- **Session state is in-memory** — restarting either backend process drops
  all in-flight conversations and the failed-attempt counters. Acceptable
  for this exercise; would need Redis or similar for real deployment (see
  `PRODUCTION_CONSIDERATIONS.md`).
- **No automated conversation-level tests** — `tests/` covers the pure
  booking-reference validation logic and the confirmation-gate/escalation
  guard logic (deterministic, no network calls), which is the
  highest-value, lowest-effort thing to unit test. It does not cover the
  full multi-turn agent conversation end-to-end (that would need mocking
  the LLM itself, or recording and replaying real Groq responses — judged
  as more effort than value for this exercise; manual testing against the
  live API stood in for it, and `EXAMPLE_CONVERSATIONS.md` captures real
  transcripts from that testing).
- **Groq/Llama tool-calling is occasionally flaky** — a small percentage of
  turns produce a malformed function call instead of a structured one (see
  README troubleshooting). Mitigated (`disable_aiohttp_transport`, explicit
  `tool_choice="auto"`) but not eliminated — a known characteristic of this
  specific model/provider combination, not an application bug.
- **`chatagent/tool.py` and `voiceagent/luggage_api.py` duplicate logic** —
  a deliberate tradeoff explained in `DESIGN_NOTES.md`, but it does mean a
  future change to the booking-API integration (e.g. a new error status to
  handle) needs to land in both files.
- **No auth on any endpoint** — `/chat`, `/create-web-call` are open. Fine
  for a local/demo exercise; not fine for anything real (see
  `PRODUCTION_CONSIDERATIONS.md`).

## If I had more time

- Shared `booking_api` package imported by both agents instead of two
  parallel files, once the state-injection difference has a clean common
  interface.
- Persist session/call state to Redis so either backend can restart without
  losing in-flight conversations.
- Record-and-replay tests for the full agent conversation loop, so the
  Groq-flakiness mitigation has a regression test instead of just manual
  verification.
- Expand the evaluation dataset with the direct-human-request scenario Call 4
  surfaced (a customer who skips the booking flow entirely and asks for a
  human) as a permanent scenario, since it wasn't in the original set.
