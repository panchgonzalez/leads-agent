# Deployment Guide

Leads Agent is a small API that receives Slack webhooks at `POST /slack/events`. Slack requires a **public HTTPS URL**, which you can achieve via:

- **Local development**: Tailscale Funnel (no static IP needed)
- **Production (EC2)**: Static IP + domain + Caddy for automatic HTTPS

Both approaches use Docker Compose.

---

## Prerequisites

| Requirement | Local | EC2 |
|-------------|:-----:|:---:|
| Docker + Compose | ✓ | ✓ |
| Slack App configured ([see README](../README.md#slack-app-setup)) | ✓ | ✓ |
| Tailscale installed | ✓ | - |
| Static IP + domain | - | ✓ |
| Ports 80/443 open | - | ✓ |

---

## Option A: Local Development (Tailscale Funnel)

Use this when you want to run the bot from your local machine without exposing ports to the internet.

### 1. Clone and configure

```bash
git clone <YOUR_REPO_URL> leads-agent
cd leads-agent

# Create .env with your secrets (see README for required vars)
cp .env.example .env
# Edit .env with your credentials
chmod 600 .env
```

### 2. Start the service

```bash
docker compose up -d --build
curl -f http://127.0.0.1:8000/  # Verify it's running
```

### 3. Expose via Tailscale Funnel

Tailscale Funnel creates a public HTTPS URL that proxies to your local service.

```bash
# Check your Tailscale version for exact syntax
tailscale version
tailscale funnel --help

# Typical command (may vary by version)
tailscale funnel 8000
```

This gives you a public URL like `https://your-machine.tailnet-name.ts.net/`.

### 4. Configure Slack

Set your Slack App's **Event Subscriptions → Request URL** to:

```
https://your-machine.tailnet-name.ts.net/slack/events
```

### Notes

- Funnel must stay running for Slack to reach your bot
- Your machine must be online and connected to Tailscale
- Good for development and testing; for always-on production, use EC2

---

## Option B: EC2 Production (Static IP + Caddy)

Use this for always-on production deployment with automatic HTTPS via Let's Encrypt.

### 1. DNS setup

Create a DNS **A record** pointing your domain to the EC2 static IP:

```
leads.example.com → 1.2.3.4 (your EC2 Elastic IP)
```

### 2. Security group

Ensure inbound rules allow:

- **TCP 80** (HTTP, for Let's Encrypt challenge)
- **TCP 443** (HTTPS, for Slack webhooks)

### 3. Clone and configure on EC2

```bash
sudo mkdir -p /opt/leads-agent
sudo chown -R "$USER":"$USER" /opt/leads-agent
cd /opt/leads-agent

git clone <YOUR_REPO_URL> .

# Create .env with your secrets
cp .env.example .env
# Edit .env with your credentials
chmod 600 .env
```

### 4. Configure Caddy

Edit `deploy/Caddyfile` and replace `your-domain.example` with your actual domain:

```bash
# deploy/Caddyfile
leads.example.com {
  encode gzip
  reverse_proxy primary:8000
}
```

### 5. Enable Caddy in docker-compose.yml

Uncomment the Caddy service and volumes:

```yaml
services:
  primary:
    # ... existing config ...

  caddy:
    image: caddy:2
    container_name: caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./deploy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - primary

volumes:
  caddy_data:
  caddy_config:
```

### 6. Deploy

```bash
docker compose up -d --build
docker compose logs -f caddy  # Watch for successful cert acquisition
```

Caddy automatically obtains and renews Let's Encrypt certificates.

### 7. Configure Slack

Set your Slack App's **Event Subscriptions → Request URL** to:

```
https://leads.example.com/slack/events
```

---

## Operations

### View logs

```bash
docker compose logs -f primary  # Application logs
docker compose logs -f caddy    # Caddy/HTTPS logs (if using)
```

### Update/deploy new version

```bash
cd /opt/leads-agent
git pull
docker compose up -d --build
docker compose logs -f primary
```

### Rollback

```bash
cd /opt/leads-agent
git checkout <previous_sha>
docker compose up -d --build
```

### Restart

```bash
docker compose restart primary
```

---

## Logfire (Observability)

Logfire provides tracing and observability for lead processing.

### Get your token

1. Go to [logfire.pydantic.dev](https://logfire.pydantic.dev/)
2. Create or select a project
3. Go to **Project Settings → Write Tokens → Create Write Token**

### Configure

Add to your `.env` file:

```bash
LOGFIRE_TOKEN=your-write-token-here
```

The token is passed to the container via docker-compose's `env_file` directive.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Caddy fails to get certificate | Verify DNS A record resolves; check ports 80/443 are open |
| "Invalid request" from Slack | Check `SLACK_SIGNING_SECRET`; ensure server clock is synced (`timedatectl`) |
| Container won't start | Check logs: `docker compose logs primary` |
| Funnel not working | Verify Tailscale is connected: `tailscale status` |
