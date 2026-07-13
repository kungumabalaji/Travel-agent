Production Considerations
What I'd change or add before deploying this to support thousands of customers a day
Scalability
•	Serve the model with vLLM for request queuing and continuous batching, so throughput holds up under load instead of degrading.
•	Autoscale the inference layer up and down with traffic instead of running fixed capacity.
•	Use model compression techniques where they make sense — distillation, pruning, and quantization — to bring latency and cost down for the high-volume paths.
•	Speculative decoding (small draft model + large model) to cut reasoning latency without swapping to a weaker model outright.
•	For the agentic loop, keep an eye on latency at each retrieval/tool-call step, not just the end-to-end response — a slow step anywhere in the loop compounds across turns.
•	RAG retrieval using both dense and sparse embeddings, so exact terms (fare codes, references) aren't missed by dense-only matching.
Monitoring and Observability
I'd split this into system logs and user/conversation logs, since they're used differently.
•	System logs — Loguru, for infra-level logging (errors, request timing, service health).
•	User/conversation logs — LangSmith, for tracing individual conversations and debugging where a run went wrong.
•	For tracking quality over time: LLM-as-a-judge for scoring conversations at scale, with RLHF and DPO to feed that signal back into the model.
•	Also worth building on the factual-vs-faithful research direction — using reinforcement learning with metacognitive feedback so the model can score how faithful its own answer is to the source data (0–1), not just whether it sounds correct.
Security
•	Guardrail model in front of the main model (e.g., a Llama-Guard-style model) to catch unsafe or out-of-scope input/output.
•	Firewall rules restricting which ports/services are reachable.
•	TLS on all endpoints.
•	Prompt-injection checks on incoming input before it reaches the tool-calling layer.
•	Role-based authentication so only the right systems/users can call sensitive endpoints (e.g., Add Luggage).
•	Rate limits per user/session to prevent abuse.
•	Consider self-hosting on open-source models for parts of the flow where data residency/privacy matters, rather than sending everything to a third-party API.
Reliability
•	Keep improving the model over time with fine-tuning and reinforcement learning based on real production data, not just the initial prompt.
•	Give the assistant internet search as a fallback so it isn't stuck with stale information for things outside the booking API's scope.
•	Post-training/refresh cycles, so the model doesn't just stay frozen at launch quality.
Testing
•	Unit tests for each tool function.
•	Manual review of sampled conversations.
•	Integration tests covering the full agentic flow end-to-end (lookup → options → confirm → add).
•	Checks for transparency (is the assistant clear about what it's doing), toxicity, and faithfulness/calibration (does it only say what the data actually supports).
Cost Optimization
•	Choose model size per task — a smaller, fine-tuned model for the routine flow, reserving larger models for harder cases, rather than one large model for everything.
•	On-demand serving for lower-traffic periods instead of always-on peak capacity.
•	Speculative decoding to cut token cost/latency on the reasoning side.
•	Rate limits to prevent runaway usage/cost from a single user or abuse pattern.
