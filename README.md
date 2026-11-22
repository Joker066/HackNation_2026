# Tap & Check

*Sprawdź, zanim uwierzysz.* A citizen-friendly fact-checking service for the **Prawdowid** task (MSZ) at HackNation 2026.

Send a message, a link or a screenshot through the web page or Discord. Tap & Check finds the checkable claims, searches an audited corpus of official sources and fact-checks (with a web-search fallback limited to allowlisted domains), and answers each claim with one of five verdicts, verbatim quotes and links. When the evidence isn't good enough, it says so instead of guessing.

- Task summary: [instruction.md](instruction.md)
- Design and build plan: [STRUCTURE.md](STRUCTURE.md)
- Source policy and retention: [docs/sources.md](docs/sources.md)
- Server deployment: [deploy/README.md](deploy/README.md)
- Demo video, slides, logo and cover: [demo/](demo/)

## Quick start

Requirements: Python 3.12 (no Node needed: the API serves the web page).

```bash
./start.sh            # API + web page on http://localhost:8000, plus the Discord bot if DISCORD_TOKEN is set
./start.sh --no-bot   # web page and API only
```

On the first run it creates `.venv`, installs the requirements, copies `.env.example` to `.env`
and builds the search index. Put your keys in `.env` (at least `ANTHROPIC_API_KEY`, or
`LLM_PROVIDER=fake` to run offline), then start it again. Stop everything with Ctrl+C.

## Running the parts manually

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
../.venv/bin/python -m crawlers.run --all          # official sources (RCB, Policja, CERT, SOK, UM Gdynia, gov.pl pages)
../.venv/bin/python -m scripts.seed_factchecks     # fact-checks via Google Fact Check API (needs GOOGLE_FACTCHECK_API_KEY)
../.venv/bin/python -m scripts.build_index --rebuild
```

The web page is `web/index.html` (design by a teammate, wired to the API).

Run the tests (no API key needed):

```bash
cd backend && ../.venv/bin/python -m pytest
```

Run the evaluation set (needs `ANTHROPIC_API_KEY`; results go to `eval/results/`):

```bash
.venv/bin/python eval/run_eval.py
```

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/check` | Check text, a URL or an image: `{"text": "...", "url": "...", "image": "<base64>", "channel": "web", "session_id": "..."}` |
| `GET /api/check/{id}` | Fetch a stored result (used by links shared from Discord) |
| `GET /api/warnings` | Latest CERT Polska advisories from the corpus |
| `GET /`, `GET /r/{id}` | Web page, and shared result links |
| `DELETE /api/session/{id}` | Delete all stored checks for a session |
| `GET /api/health` | Status, active model provider, corpus size |
| `GET /api/logs`, `GET /api/metrics` | Audit log and metrics (header `X-Admin-Token`) |

## Status

All planned features are built: web page, Discord bot, text/link/screenshot input, EUvsDisinfo matching,
web-search fallback. Latest evaluation on 30 cases: macro-F1 0.97, accuracy 97%, abstention 100%,
injection resistance 100%, median 7.2 s, $0.004 per check. Details in [STRUCTURE.md](STRUCTURE.md#7-status).
