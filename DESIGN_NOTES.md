Design Notes
Luggage Support Assistant — Chat Agent & Voice Agent
1. Overall Solution Design
The solution is composed of two complementary agents that share the same underlying booking and luggage APIs: a Chat Agent and a Voice Agent. Both agents expose the same four core capabilities — retrieve booking details, retrieve luggage options, add luggage, and escalate to a human agent — but are built on different frameworks suited to their channel (text vs. voice).
1.1 Chat Agent
The Chat Agent is built using the Google Agent Development Kit (ADK). It performs soft validation on the booking reference number rather than enforcing a fixed format, so that a range of realistic reference styles can still be accepted and normalized.
The agent is driven by a strict system prompt that defines:
•	Persona and main goal
•	Booking reference rules
•	Booking modification rules
•	Intent rules
•	Luggage option rules
•	Information limits
•	Confirmation rules
•	Conversation style
•	Closing rules
The underlying LLM is Groq Llama 3.3 70B Versatile, run at a temperature of 0.3 to keep responses consistent and predictable. Conversation state is held in an in-memory runner for the duration of the session.
The agent exposes four Python tool functions to the ADK runtime:
•	Get Booking Details
•	Get Luggage Options
•	Add Luggage
•	Escalate to Human
ADK reads each tool's function name, docstring, parameters, and return type to decide when and how to call it.
1.2 Voice Agent
The Voice Agent is built on the Retell AI SDK, which provides the speech-to-text (STT) model, a GPT reasoning model, and a text-to-speech (TTS) model in one pipeline. The same four capabilities (Get Booking Details, Get Luggage Options, Add Luggage, Escalate to Human) are exposed to Retell as function/tool schemas with their parameters.
Supporting infrastructure for the Voice Agent includes:
•	Create Web Call endpoint — initiates the call and returns a browser access token.
•	Logger — initialized alongside the call to capture session activity.
•	Webhook endpoint — runs on a separate backend and receives call events.
Reasoning uses GPT-5.1, and the voice output is configured with a British accent.
2. Key Architectural Decisions
2.1 Why Google ADK for the Chat Agent
Google's Agent Development Kit was chosen for the text channel because it is purpose-built for tool-calling agents: it reads a Python function's name, docstring, parameters, and return type directly to decide when and how to call it, so no separate tool-schema definition has to be hand-maintained alongside the code. This kept the four tools (Get Booking Details, Get Luggage Options, Add Luggage, Escalate to Human) declarative and easy to extend, and let the strict system prompt (persona, booking-reference rules, modification rules, intent rules, confirmation rules, etc.) drive the agent's behavior predictably.
2.2 Why Groq Llama 3.3 70B Versatile, and why temperature 0.3
Groq's inference of Llama 3.3 70B Versatile was selected for the Chat Agent for its low-latency, high-throughput inference, which keeps text responses fast without needing a paid frontier model for what is largely a rules-following, tool-calling task rather than open-ended reasoning.
Temperature was set to 0.3, rather than a higher default, specifically because the assistant has to follow a strict, rule-heavy prompt (booking-reference rules, confirmation rules, escalation rules). A low temperature reduces response variance and the chance of the model deviating from those rules or hallucinating booking details, at the cost of slightly less varied/natural phrasing — an acceptable trade-off for a support assistant where consistency and correctness matter more than conversational flair.
2.3 Why Retell AI for the Voice Agent
Retell AI was chosen for the voice channel because it packages the full voice pipeline — STT, an LLM for reasoning, and TTS — behind one SDK, along with production-grade voice features that would otherwise have to be built from scratch: a Create Web Call endpoint for issuing browser access tokens, configurable interruption sensitivity and response eagerness, real-time transcription with noise and background-speech removal, and built-in call logging (duration, cost, latency, sentiment, session outcome). This let the voice agent focus on the domain logic (the four tools, exposed as function schemas) while Retell handled the latency-sensitive telephony/streaming layer.
GPT-5.1 was used as Retell's reasoning model specifically for the voice channel because voice interactions are far more latency-sensitive and less forgiving of hesitation or error than text, so a stronger, more reliable reasoning model was prioritized over the cheaper model used for chat. A British accent was configured for the TTS voice to match the intended brand/customer experience.
2.4 Other Key Decisions
•	Two-agent architecture sharing one API surface — the Chat Agent (Google ADK) and Voice Agent (Retell AI) are built independently but both call the same four underlying operations, avoiding duplicated business logic.
•	Soft validation over rigid formats — booking references are normalized (uppercased, treated as an alphanumeric token) rather than matched against one fixed pattern, so more real-world reference formats are accepted.
•	In-memory session state — conversation history for the Chat Agent is kept in an in-memory runner, keeping the implementation simple for the scope of this assignment.
•	Two-step confirmation before purchase — luggage options are fetched and shown first; only after the customer confirms does the same flow proceed to the final add-luggage API call, preventing accidental purchases.
•	Separate microservice deployment for the Voice Agent — the Voice Agent backend is deployed independently on Render and wired into the Retell SDK via a custom API endpoint, isolating voice-specific infrastructure (webhooks, latency-sensitive calls) from the Chat Agent.
•	Voice tuning parameters — interruption sensitivity, response eagerness, and real-time transcription (with noise and background-speech removal) are configurable, and the transcription model is set to optimize for speed to minimize perceived latency.
2.5 Why an Evaluation Pipeline
An evaluation pipeline was created to give a consistent, repeatable way to judge how well the assistant was actually performing against the rules defined in the prompt (booking-reference handling, confirmation flow, escalation triggers, etc.), rather than relying on ad-hoc, subjective impressions of individual conversations.
Each conversation is scored per category using the formula:
Category Score = Category Weight − Σ (deductions for each issue found in that category)
Each category (e.g., booking handling, luggage flow, escalation behavior, conversation quality) starts at its assigned weight, and points are deducted for each specific issue identified in that category, with deduction size roughly proportional to the severity of the issue and the weight of the category it falls under.
Deductions are assigned qualitatively by the reviewer, based on direct evidence pulled from the conversation transcript and the backend logs (API calls, responses, errors) rather than being inferred or assumed. This makes it a structured manual scoring method grounded in evidence — not a statistical or automated metric — which was a deliberate choice: the failure modes that matter most here (e.g., confirming a purchase without customer consent, missing an escalation trigger, hallucinating booking details) are rule-based and contextual, and are more reliably caught by evidence-based human review against a fixed rubric than by a generic automated scoring model at this stage of the project.
3. How the Assistant Uses the Provided APIs
All outbound calls are built as complete API URLs, sent as POST requests with a ten-second timeout, logged (request and response), and parsed as JSON. Connection failures and timeout failures are both caught and returned to the agent as structured error information.
3.1 Get Booking Details
This is always the first tool called once the customer provides a booking reference. The tool soft-validates and normalizes the reference before calling the API — it does not enforce any specific format, since the booking-lookup API itself is treated as the source of truth for whether a reference is real. The response is used to determine:
•	Whether the booking was found
•	Passenger details
•	Flight details
•	Whether the booking can be modified
•	Whether the booking should be escalated to a human
Failed-lookup attempts are tracked in session state. Escalation is triggered only after three consecutive failed lookups, not three failures across the whole conversation — a successful lookup resets the failure streak back to zero. This avoids escalating a customer who simply mistyped a reference once or twice before getting it right.
3.2 Get Luggage Options
This tool is only called after Get Booking Details has confirmed the booking exists and can be modified. It sends the booking reference to the ancillary-services API, which returns a structure containing service definitions, ancillary services, passengers, flight segments, prices, and availability.
The raw API prices and books each (bag type, passenger) combination as its own line item, nested inside ancillaryServices[].selectionOptions[]. The tool flattens this into one option per passenger per bag type — so the same bag type appears once per passenger it's available for, each with its own option_id — and caches the full item spec needed for the real add-luggage request (service definition ID, ancillary service ID, passenger reference IDs, flight-segment reference IDs, expected price) in session state, keyed by that option_id. This means the assistant only ever has to echo back a simple option_id; it never has to reconstruct the nested API shape itself.
Each simplified option returned to the assistant contains:
•	Option ID
•	Luggage name or weight
•	Price
•	Currency
•	Passenger reference
•	Applicable flight segment(s)
If the booking has multiple passengers, the assistant is required to ask the customer which passenger(s) the luggage is for — cross-referencing passenger names from the earlier Get Booking Details result — before calling Add Luggage. The assistant then presents the relevant option(s) and asks for confirmation before proceeding.
3.3 Add Luggage
Once the customer confirms an option by its option_id, the cached item spec from Get Luggage Options is used to submit the final request, which contains:
•	Booking reference
•	Idempotency key
•	Service definition ID
•	Ancillary service ID
•	Passenger reference ID(s)
•	Flight-segment reference ID(s)
•	Quantity
•	Expected price
The idempotency key protects against duplicate purchases if the request is retried after a network issue.
3.4 Rules Kept Per API / Tool
Each of the four tools (Get Booking Details, Get Luggage Options, Add Luggage, Escalate to Human) carries its own scoped rules, enforced through a combination of the tool's docstring (read by ADK) and the system prompt, rather than one generic rule set applied to all four:
•	API 1 — Get Booking Details: always called first on any booking reference; soft-validate/normalize before calling; escalate only on 3 consecutive failures (streak resets on success).
•	API 2 — Get Luggage Options: only called after a booking is confirmed to exist and be modifiable; must resolve which passenger(s) the request applies to before proceeding; present options and get confirmation before booking.
•	API 3 — Add Luggage: only called after explicit customer confirmation of a specific option_id; always sent with an idempotency key and the expected price to guard against duplicate or mismatched charges.
•	API 4 — Escalate to Human: called immediately whenever any escalation trigger fires (see Section 4.2), regardless of which other tool was in progress.
3.5 Request/Response Validation (Pydantic)
Each of the four API integrations is backed by its own Pydantic models for both the outbound request payload and the inbound response body, rather than one shared model — since the booking, luggage-options, add-luggage, and escalation endpoints each have a materially different shape. This gives type-safe parsing and validation at the API boundary before data reaches the tool logic or the LLM.
Business rules on top of that (e.g., when a tool is allowed to be called, what must be confirmed first, when to escalate) are deliberately kept in the prompt and tool docstrings rather than baked into the Pydantic models themselves — Pydantic is used strictly for data-shape validation, while conversational/sequencing rules are left to the agent's reasoning layer, which is easier to iterate on without touching the API integration code.
3.6 Voice Agent Tool Wiring
The same four operations (Get Booking Details, Get Luggage Options, Add Luggage, Escalate to Human) are defined as function schemas inside Retell, and are backed by the deployed backend on Render. The webhook endpoint on that backend receives Retell's call events and drives the same tool logic used by the Chat Agent.
4. Error Handling and Escalation Strategy
4.1 Error Handling
•	A ten-second timeout is applied to every outbound API request.
•	Every request and response is logged for traceability.
•	JSON responses are parsed and validated before being handed back to the agent.
•	Connection failures are caught explicitly and reported as structured errors.
•	Timeout failures are caught explicitly and reported as structured errors.
•	HTTP error status codes are surfaced with the response body for debugging.
4.2 Escalation Triggers
The assistant escalates the conversation to a human agent when any of the following occur:
•	Three consecutive invalid booking references
•	A booking that cannot be modified
•	No available luggage options
•	Booking-service failures
•	Luggage-removal or refund requests
•	Price disputes
•	Requests outside the scope of luggage support
•	A direct request to speak to a human agent
5. Assumptions and Trade-offs
•	In-memory conversation state — assumed acceptable for this assignment's scope; a production deployment would need persistent, session-scoped storage (e.g., Redis) to survive restarts and scale across instances.
•	Soft validation of booking references — trades strict format enforcement for flexibility, accepting a wider range of real-world reference formats at the cost of catching fewer malformed inputs up front.
•	Separate deployments per agent — the Voice Agent backend runs as its own microservice on Render rather than being merged with the Chat Agent, trading some deployment overhead for cleaner separation of concerns and independent scaling.
•	Model choice per channel — Groq Llama 3.3 70B Versatile was used for the Chat Agent (cost/latency-efficient for text), while GPT-5.1 was used for Voice Agent reasoning to prioritize the low latency and reliability voice interactions require.
•	Two-step confirm-then-commit flow — assumes the customer will explicitly confirm before a luggage purchase is finalized; this adds one extra turn to the conversation but reduces the risk of unintended charges.
•	Voice cost and latency assumptions — approximate figures used for planning were: reasoning (GPT-5.1) ≈ $0.040/min with 500–800 ms latency; TTS ≈ $0.01/min with ~450 ms latency; STT ≈ $0.005/min with 20–200 ms latency. These are estimates for capacity/cost planning, not guaranteed production figures.
•	Post-call analytics as a follow-up item — session logs already capture duration, channel, cost, latency, session ID, end reason, sentiment (positive/negative/neutral), session outcome, and end-to-end latency; deeper post-call analysis is scoped as future work rather than part of this initial build.
•	Per-endpoint Pydantic models — assumes it's worth maintaining separate Pydantic request/response models for each of the four API integrations rather than one generic schema; this adds some duplication across the four endpoints but gives stricter, endpoint-specific validation and clearer error messages when a response shape doesn't match expectations.
