#!/usr/bin/env bash
# Tap & Check: one command to start everything.
#
#   ./start.sh              API + web page (http://localhost:8000) + Discord bot (if DISCORD_TOKEN is set)
#   ./start.sh --no-bot     API + web page only
#   PORT=9000 ./start.sh    use another port
#
# First run: creates .venv, installs requirements, creates .env from .env.example and builds
# the search index. Stop everything with Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
RUN_BOT=1
for arg in "$@"; do
  case "$arg" in
    --no-bot) RUN_BOT=0 ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)"; exit 2 ;;
  esac
done

say() { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }

# --- 1. Python environment -------------------------------------------------------
if [ ! -x .venv/bin/python ]; then
  command -v python3 >/dev/null || fail "python3 not found (Python 3.12 required)"
  say "Creating .venv and installing requirements (first run)…"
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi

# --- 2. Configuration -------------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  say "Created .env from .env.example. Add ANTHROPIC_API_KEY (or set LLM_PROVIDER=fake to run offline)."
fi
env_has() { grep -qE "^$1=.+" .env; }
if ! env_has ANTHROPIC_API_KEY && ! grep -qE "^LLM_PROVIDER=fake" .env; then
  say "Warning: no ANTHROPIC_API_KEY in .env. Checks will return a technical error until it is set."
fi

# --- 3. Retention and search index ---------------------------------------------------
# Delete full-text articles past the retention period (docs/sources.md); rebuilds the index if needed.
(cd backend && ../.venv/bin/python -m scripts.purge_sources --quiet --rebuild-index | tail -1) || true
if [ ! -f var/corpus.db ]; then
  say "Building the search index from corpus/text_sources/…"
  (cd backend && ../.venv/bin/python -m scripts.build_index --rebuild | tail -1)
fi

# --- 4. Start the services ----------------------------------------------------------
if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
  fail "Port $PORT is already in use. Stop the other server first (e.g. pkill -f 'uvicorn app.main:app') or use PORT=…"
fi

PIDS=()
cleanup() {
  trap - INT TERM EXIT
  if [ ${#PIDS[@]} -gt 0 ]; then
    say "Stopping…"
    kill "${PIDS[@]}" 2>/dev/null || true
    wait "${PIDS[@]}" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

say "Starting API + web page on port $PORT…"
# --proxy-headers: behind a proxy/tunnel, use the visitor's real IP (per-visitor rate limit)
(cd backend && exec ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips 127.0.0.1) &
PIDS+=($!)

for _ in $(seq 1 60); do
  if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then break; fi
  kill -0 "${PIDS[0]}" 2>/dev/null || fail "The API failed to start (see the messages above)."
  sleep 0.5
done

if [ "$RUN_BOT" = 1 ] && env_has DISCORD_TOKEN; then
  say "Starting Discord bot…"
  (cd backend && API_BASE_URL="http://localhost:$PORT" exec ../.venv/bin/python -m channels.discord_bot) &
  PIDS+=($!)
elif [ "$RUN_BOT" = 1 ]; then
  say "No DISCORD_TOKEN in .env: starting without the Discord bot."
fi

say "Ready: http://localhost:$PORT  (API docs: http://localhost:$PORT/docs). Press Ctrl+C to stop."
# If any service exits, stop the others too.
wait -n "${PIDS[@]}"
say "A service stopped; shutting down the rest."
