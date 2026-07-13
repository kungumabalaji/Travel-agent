# Production Considerations

What this exercise deliberately doesn't do, and what would need to change
before any of this touched real customers or real bookings.

## Secrets & configuration

- `.env` files are fine for local dev; a real deployment needs a secrets
  manager (AWS Secrets Manager, GCP Secret Manager, Vault) and the API keys
  rotated out of anything that ever touched a `.env` file on a laptop.
- `RETELL_API_KEY` and `GROQ_API_KEY` are currently loaded once at process
  start with no rotation story — a leaked key means editing `.env` and
  restarting, with no audit trail of who had access.

## AuthN/AuthZ

- `/chat`, `/create-web-call`, `/functions`, `/webhook` have no
  authentication beyond `/webhook` and `/functions`' Retell signature check.
  Anyone who finds the chat/voice URLs can start a session as any
  "customer." A real deployment needs the frontend to authenticate the
  actual logged-in loveholidays customer and pass that identity through,
  so `get_booking_details` can be scoped to bookings that customer actually
  owns — right now anyone who knows a valid booking reference can query or
  modify it, which is fine for a demo dataset and not fine for real PII.

## Session & state persistence

- Both agents hold conversation/call state in plain Python memory
  (`InMemorySessionService` for chat, a `call_id`-keyed dict for voice).
  Restarting the process loses every in-flight conversation and resets
  escalation counters. A real deployment needs shared state (Redis,
  DynamoDB) so state survives restarts/deploys and multiple backend
  instances can serve the same conversation.
- Nothing currently expires old sessions — `KNOWN_SESSIONS` and the voice
  agent's per-call dicts grow for as long as the process runs (voice does
  clean up on `call_ended`; chat does not). A production version needs TTL
  eviction.

## Reliability

- The intermittent Groq/Llama malformed-tool-call issue (see README) is
  currently a "the customer might see a weird failure and have to retry"
  risk. Production should catch that specific failure mode and retry the
  LLM call automatically once before surfacing anything to the customer.
- No circuit breaker or backoff on the booking API — if it degrades, every
  request just waits out the 10s timeout. A real deployment needs backoff,
  and probably a fallback message distinct from "something went wrong" for
  "the booking system itself is down" vs. "this specific request failed."

## Observability

- Logging goes to stdout via Python's `logging` module — fine for `docker
  logs` during development, not fine for actually operating this. Needs
  structured logging (JSON) shipped to a real log platform, plus metrics
  (request latency, tool-call error rate, escalation rate) and alerting on
  the Groq-flakiness failure mode specifically, since it's a known
  recurring issue.
- No tracing across the chat-agent → tool.py → booking-API hop or the
  voice-agent → Retell → `/functions` hop, so a slow/failing conversation
  can't be traced end-to-end without reading raw logs.

## Data & compliance

- Passenger names, dates of birth, and booking details flow through Groq
  (a third-party LLM provider) and Retell (a third-party voice provider).
  Before handling real customer data, this needs a data processing
  agreement with both, and a decision about what's allowed to be sent to an
  LLM at all (e.g., should DOB ever leave the booking system, even to
  answer "how old is this passenger").
- Voice calls are, by nature, recorded/transcribed by Retell. Real usage
  needs explicit call-recording consent language and a retention policy for
  transcripts.
- No PII redaction in logs — booking references, names, and reasons for
  escalation are all logged in plaintext.

## Cost & abuse controls

- Nothing currently rate-limits `/chat` or `/create-web-call` — either
  could be hit in a loop to run up Groq/Retell usage costs.
- No per-customer or per-IP throttling, no CAPTCHA/bot protection on the
  public-facing widgets.

## Testing & deployment

- No CI pipeline — tests exist (`tests/`) but nothing runs them
  automatically on push/PR.
- No containerization — a real deployment would containerize each service
  (`chatagent`, `voiceagent`) rather than `python main.py` on a laptop or a
  single VM.
- Blue/green or canary deploy story is nonexistent; a bad prompt change
  currently means editing `agent.py` and restarting the process directly.
