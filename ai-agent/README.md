# ai-agent
For now the agent lives inside core-api as a module (`core-api/app/agent/`): `safety.py` (emergency rules),
`context.py` (history to Gemini format), `gemini.py` (API client), `prompt.py`, `service.py` (entry point).
It has no dependency on the web layer, so it can be moved into this folder as its own service when the
message queue arrives (T9-T11).
