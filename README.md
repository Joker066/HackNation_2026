# Tap & Check

*Sprawdź, zanim udostępnisz.* A citizen-friendly fact-checking service for the **Prawdowid** task (MSZ) at HackNation 2026.

Send a message or link through the web page or Discord. Tap & Check finds the checkable claims, searches an audited corpus of official sources and fact-checks, and answers each claim with one of five verdicts, verbatim quotes and links. When the evidence isn't good enough, it says so instead of guessing.

- Task summary: [instruction.md](instruction.md)
- Design and build plan: [STRUCTURE.md](STRUCTURE.md)

## Running locally

Requirements: Python 3.12 (no Node needed: the API serves the web page).

```bash
# 1. Install
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env            # set ANTHROPIC_API_KEY (or LLM_PROVIDER=fake to run offline)

# 2. Build the search index from the saved documents in corpus/text_sources/
cd backend
../.venv/bin/python -m scripts.build_index --rebuild

# 3. Start the API + web page: open http://localhost:8000 (API docs at /docs)
../.venv/bin/uvicorn app.main:app --port 8000

# 4. Optional: Discord bot (needs DISCORD_TOKEN in .env), in another terminal
cd backend && ../.venv/bin/python -m channels.discord_bot
```

Refresh the corpus (optional; the saved documents are in the repository):

```bash
cd backend
../.venv/bin/python -m crawlers.run --all          # official sources (RCB, Policja, CERT, SOK, UM Gdynia)
../.venv/bin/python -m scripts.seed_factchecks     # fact-checks via Google Fact Check API (needs GOOGLE_FACTCHECK_API_KEY)
../.venv/bin/python -m scripts.build_index --rebuild
```

The web page is `web/index.html` (design by a teammate, wired to the API).

Run the tests (no API key needed):

```bash
cd backend && ../.venv/bin/python -m pytest
```

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/check` | Check text or a URL: `{"text": "...", "channel": "web", "session_id": "..."}` |
| `GET /api/check/{id}` | Fetch a stored result (used by links shared from Discord) |
| `GET /api/warnings` | Latest CERT Polska advisories from the corpus |
| `GET /`, `GET /r/{id}` | Web page, and shared result links |
| `DELETE /api/session/{id}` | Delete all stored checks for a session |
| `GET /api/health` | Status, active model provider, corpus size |
| `GET /api/logs`, `GET /api/metrics` | Audit log and metrics (header `X-Admin-Token`) |

## Status

Work in progress. See the build order in [STRUCTURE.md](STRUCTURE.md#7-build-order).
