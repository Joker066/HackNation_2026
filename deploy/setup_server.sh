#!/usr/bin/env bash
# Set up Tap & Check on a fresh Ubuntu 24.04 server (run as root, from /opt/tapcheck).
#
#   sudo bash deploy/setup_server.sh                 # address: <server-ip>.sslip.io (free, HTTPS)
#   sudo TAPCHECK_HOST=tapcheck.example.pl bash deploy/setup_server.sh   # your own domain
#
# Expects the code in /opt/tapcheck and the secrets in /opt/tapcheck/.env (see deploy/README.md).
# Safe to run again after an update.
set -euo pipefail

APP=/opt/tapcheck
say() { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || fail "Run as root (sudo)."
[ -f "$APP/backend/app/main.py" ] || fail "Code not found in $APP (copy the repository there first)."
[ -f "$APP/.env" ] || fail "$APP/.env missing (copy your .env there; never commit it)."
grep -qE '^ANTHROPIC_API_KEY=.+' "$APP/.env" || fail "ANTHROPIC_API_KEY is not set in $APP/.env"

# --- address ------------------------------------------------------------------------
if [ -z "${TAPCHECK_HOST:-}" ]; then
  IP=$(curl -4 -fsS https://api.ipify.org || true)
  [ -n "$IP" ] || fail "Could not detect the public IPv4 address; set TAPCHECK_HOST."
  TAPCHECK_HOST="${IP//./-}.sslip.io"   # resolves to the IP; Caddy gets a real certificate for it
fi
say "Public address: https://$TAPCHECK_HOST"

# --- packages -----------------------------------------------------------------------
say "Installing packages…"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip caddy ufw curl >/dev/null

# --- user, files, Python environment ---------------------------------------------------
id tapcheck >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin tapcheck
mkdir -p "$APP/var"
chown -R tapcheck:tapcheck "$APP"
chmod 600 "$APP/.env"
say "Creating the Python environment…"
sudo -u tapcheck python3 -m venv "$APP/.venv"
sudo -u tapcheck "$APP/.venv/bin/pip" install -q --upgrade pip
sudo -u tapcheck "$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"

# --- configuration: public links point to the server ---------------------------------------
set_env() {  # set KEY=VALUE in .env (replace or append)
  if grep -qE "^$1=" "$APP/.env"; then sed -i "s|^$1=.*|$1=$2|" "$APP/.env"; else echo "$1=$2" >> "$APP/.env"; fi
}
set_env PUBLIC_BASE_URL "https://$TAPCHECK_HOST"
set_env API_BASE_URL "http://127.0.0.1:8000"

# --- services -------------------------------------------------------------------------
say "Installing services…"
install -m 644 "$APP"/deploy/tapcheck-{api,bot,refresh}.service "$APP"/deploy/tapcheck-refresh.timer /etc/systemd/system/
sed "s|{\$TAPCHECK_HOST}|$TAPCHECK_HOST|" "$APP/deploy/Caddyfile.template" > /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable --now tapcheck-api tapcheck-refresh.timer
if grep -qE '^DISCORD_TOKEN=.+' "$APP/.env"; then
  systemctl enable --now tapcheck-bot
else
  say "No DISCORD_TOKEN in .env: Discord bot not started."
fi
systemctl reload caddy || systemctl restart caddy

# --- firewall: only SSH and HTTP(S) -----------------------------------------------------------
ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

# --- check ------------------------------------------------------------------------------
say "Waiting for the API (index build can take a minute)…"
for _ in $(seq 1 90); do curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break; sleep 2; done
curl -fsS http://127.0.0.1:8000/api/health >/dev/null || fail "API did not start: journalctl -u tapcheck-api -n 50"
say "Ready: https://$TAPCHECK_HOST  (the certificate may take ~30 s on the first visit)"
say "Logs: journalctl -u tapcheck-api -f   |   journalctl -u tapcheck-bot -f"
