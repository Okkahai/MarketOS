# Deploying MarketOS on a Hetzner server

A small always-on server (about 6 EUR per month) running the same `docker compose` stack you use locally. Sizing and the price are estimates, see "Sizing" below.

**Security first.** The web app and the API have **no login**. This guide keeps every port closed to the internet and reaches the dashboard through an SSH tunnel. Do not open ports 3000 or 8000 until a password gate exists.

## 1. Account and server (you, in the browser)

1. Create an account at https://www.hetzner.com/cloud and add a payment method.
2. On your computer, make an SSH key (Windows PowerShell or any terminal):
   ```bash
   ssh-keygen -t ed25519
   ```
   Press Enter at every question, then show the public key and copy it:
   ```bash
   cat ~/.ssh/id_ed25519.pub        # Windows: type $env:USERPROFILE\.ssh\id_ed25519.pub
   ```
3. In the Hetzner console create a project, then **Add Server**:
   - Location: Germany or Finland (the cheap CX plans exist only there)
   - Image: Ubuntu 24.04
   - Type: **CX23** (2 vCPU, 4 GB RAM)
   - SSH key: paste the public key from step 2
   - Firewall: create one that allows only inbound **TCP 22**. Nothing else.
4. Note the server's IP address.

## 2. Install Docker (on the server)

```bash
ssh root@SERVER_IP
curl -fsSL https://get.docker.com | sh
docker compose version
```

## 3. Get the code and configure

```bash
git clone https://github.com/Okkahai/MarketOS.git
cd MarketOS
cp .env.example .env
nano .env
```

Set these in `.env`:

| Setting | Value |
|---|---|
| `POSTGRES_PASSWORD` | a long random password. Set it **before the first start**, the database keeps the first one |
| `TIINGO_API_KEY` | your Tiingo token (if it was ever pasted in a chat, make a new one at tiingo.com) |
| `SEC_USER_AGENT` | your name and email |

Leave `DATABASE_URL` alone, compose builds its own.

## 4. Start

```bash
docker compose up --build -d
docker compose ps
```

All services should show `running` or `healthy`, and `migrate` should have exited with code 0. Services restart on their own after a reboot.

## 5. Open the dashboard

From your own computer, open a tunnel and leave it running:

```bash
ssh -L 3000:localhost:3000 root@SERVER_IP
```

Then browse to http://localhost:3000. On the System status page check:

- Backend ready, database and Redis ok
- the **Alerts** card is empty after the first hour of jobs (jobs show "never ran" until their first run)
- `ingest_stock_daily` succeeded
- `ingest_crypto_1m` succeeded. If your home internet blocked Coinbase, a server in Germany or Finland usually is not blocked, but verify this.

## 6. Backups

Paper-trading history cannot be recreated, so back it up. On the server:

```bash
mkdir -p /root/backups
crontab -e
```

Add this one line:

```
0 3 * * * cd /root/MarketOS && docker compose exec -T postgres pg_dump -U marketos marketos | gzip > /root/backups/marketos-$(date +\%F).sql.gz && find /root/backups -mtime +14 -delete
```

This keeps 14 days on the same server, which does not protect against losing the server. Copy the folder to your computer now and then:

```bash
scp -r root@SERVER_IP:/root/backups ./marketos-backups
```

Restore into an empty database:

```bash
gunzip -c marketos-YYYY-MM-DD.sql.gz | docker compose exec -T postgres psql -U marketos marketos
```

## 7. Updating

```bash
cd MarketOS && git pull && docker compose up --build -d
```

Migrations run automatically on start.

## Sizing

The stack needs roughly 1 GB of RAM, little CPU and 1 to 3 GB of disk in the first year. These are estimates from the service settings, not measurements. To measure, run `docker stats --no-stream` on the server after a day. CX23 (4 GB) leaves comfortable room, a 2 GB plan may run out of memory.

## What this does not cover

- No notifications. Alerts appear only on the System status page, nobody is emailed if the server stops.
- No login, so no public access. A reverse proxy with HTTPS and a password is the next step if you want to open it from a phone without a tunnel.
- This guide was written from the project's compose file and has not been run on a real server.
