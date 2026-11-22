# Deployment (any Ubuntu 24.04 server)

Runs the API + web page and the Discord bot as services, refreshes official sources every hour,
and serves everything over HTTPS through Caddy. Works on any small VPS (e.g. Hetzner, OVH,
Mikrus); choose an **EU location** (the task values transparent data-processing location).

**Server size:** 1 vCPU, 2 GB RAM, 20 GB disk is enough.

## 1. Copy the code and the secrets

From the project folder on your computer (replace `SERVER_IP`):

```bash
rsync -az --delete --exclude .venv --exclude var --exclude .git --exclude '*.docx' \
      ./ root@SERVER_IP:/opt/tapcheck/
scp .env root@SERVER_IP:/opt/tapcheck/.env      # secrets: never in git
```

## 2. Run the setup (once)

```bash
ssh root@SERVER_IP 'cd /opt/tapcheck && bash deploy/setup_server.sh'
```

It installs Python, Caddy and a firewall (SSH, 80, 443 only), creates the `tapcheck` user,
builds the search index, starts the services, and prints the public address, by default
`https://<ip-with-dashes>.sslip.io` (free, valid HTTPS certificate, no domain needed). To use
your own domain, point its DNS A record to the server and run
`TAPCHECK_HOST=your.domain bash deploy/setup_server.sh` instead.

**Stop the bot on your laptop** once the server runs it: two bots with the same token conflict.

## 3. Update after code changes

```bash
rsync -az --delete --exclude .venv --exclude var --exclude .git --exclude '*.docx' \
      --exclude .env ./ root@SERVER_IP:/opt/tapcheck/
ssh root@SERVER_IP 'chown -R tapcheck:tapcheck /opt/tapcheck && systemctl restart tapcheck-api tapcheck-bot'
```

(If `requirements.txt` changed, run the setup script again; it is safe to repeat.)

## What runs

| Unit | What |
|---|---|
| `tapcheck-api` | API + web page on 127.0.0.1:8000; rebuilds the index on start; restarts automatically |
| `tapcheck-bot` | Discord bot (only if `DISCORD_TOKEN` is set) |
| `tapcheck-refresh.timer` | hourly: crawlers (RCB, GIS, police, CERT…), retention, add new documents to the index |
| `caddy` | HTTPS (automatic certificate), reverse proxy, 8 MB request limit (screenshots) |

Logs: `journalctl -u tapcheck-api -f`, `journalctl -u tapcheck-bot -f`, `journalctl -u tapcheck-refresh`.

## Costs (judging period)

- Server: ~€4–6 per month.
- Claude API: ~$0.005 per check (about $5 per 1,000); a spend limit in the Anthropic console caps it.
- Google Fact Check, EUvsDisinfo, Discord, sslip.io, Let's Encrypt: free.
