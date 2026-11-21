# Tap & Check

*Sprawdź, zanim udostępnisz.* A citizen-friendly fact-checking service for the **Prawdowid** task (MSZ) at HackNation 2026.

Send a message or link through the web page or Discord. Tap & Check finds the checkable claims, searches an audited corpus of official sources and fact-checks, and answers each claim with one of five verdicts, verbatim quotes and links. When the evidence isn't good enough, it says so instead of guessing.

- Task summary: [instruction.md](instruction.md)
- Design and build plan: [STRUCTURE.md](STRUCTURE.md)

## Running locally

Requirements: Python 3.12, Node 20+.

```bash
# 1. Backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env            # then set ANTHROPIC_API_KEY (or LLM_PROVIDER=fake to run offline)

# 2. Build the corpus index from corpus/records/*.jsonl
cd backend
../.venv/bin/python -m scripts.build_index --rebuild

# 3. Start the API (http://localhost:8000, OpenAPI docs at /docs)
../.venv/bin/uvicorn app.main:app --port 8000

# 4. Start the web UI (http://localhost:5173), in another terminal
cd frontend && npm install && npm run dev

# 5. Optional: start the Discord bot (needs DISCORD_TOKEN in .env), in another terminal
cd backend && ../.venv/bin/python -m channels.discord_bot
```

Run the tests (no API key needed):

```bash
cd backend && ../.venv/bin/python -m pytest
```

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/check` | Check text or a URL: `{"text": "...", "channel": "web", "session_id": "..."}` |
| `GET /api/check/{id}` | Fetch a stored result (used by links shared from Discord) |
| `DELETE /api/session/{id}` | Delete all stored checks for a session |
| `GET /api/health` | Status, active model provider, corpus size |
| `GET /api/logs`, `GET /api/metrics` | Audit log and metrics (header `X-Admin-Token`) |

## Status

Work in progress. See the build order in [STRUCTURE.md](STRUCTURE.md#7-build-order).
