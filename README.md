# Leads Agent

AI-powered Slack bot that classifies inbound leads from HubSpot and researches promising ones.

When HubSpot posts a lead to your Slack channel, Leads Agent:
1. Parses contact info (name, email, company)
2. Classifies the lead using an LLM
3. **Optionally researches** promising leads via web search
4. Posts a threaded reply with results

## Classification Labels

| Label | Description |
|-------|-------------|
| 🟢 **promising** | Genuine inquiry about services or collaboration |
| 🟡 **solicitation** | Vendors, sales pitches, recruiters, partnerships |
| 🔴 **spam** | Irrelevant, automated, SEO/link-building, junk |

## Features

- **HubSpot-specific parsing** — Extracts first name, last name, email, company from HubSpot message format
- **Smart classification** — Infers company from email domain when not provided
- **Web search enrichment** — Researches promising leads (company info, contact role) using DuckDuckGo
- **Threaded replies** — Keeps channels clean by replying in threads
- **Backtesting** — Test classifier on historical leads before going live

---

## Quick Start

```bash
git clone https://github.com/yourusername/leads-agent.git
cd leads-agent

uv venv && source .venv/bin/activate
uv pip install -e .

leads-agent init   # Interactive setup
leads-agent run    # Start server
```

---

## Configuration

### Interactive Setup (Recommended)

```bash
leads-agent init
```

### Environment Variables

```bash
# Slack
export SLACK_BOT_TOKEN="xoxb-..."
export SLACK_SIGNING_SECRET="..."
export SLACK_CHANNEL_ID="C..."

# LLM (OpenAI by default)
export OPENAI_API_KEY="sk-..."
export LLM_MODEL_NAME="gpt-4o-mini"  # optional

# Behavior
export DRY_RUN="true"  # Set to "false" to post replies
```

### Verify Configuration

```bash
leads-agent config
```

---

## Slack App Setup

### Using the Manifest (Recommended)

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App** → **From an app manifest**
3. Paste [`slack-app-manifest.yml`](slack-app-manifest.yml)
4. Replace `YOUR_DOMAIN` with your server URL
5. Install to workspace

**Get credentials:**

| Credential | Location |
|------------|----------|
| `SLACK_BOT_TOKEN` | OAuth & Permissions → Bot User OAuth Token |
| `SLACK_SIGNING_SECRET` | Basic Information → Signing Secret |
| `SLACK_CHANNEL_ID` | Right-click channel → View details → Copy ID |

**Invite the bot:**

```
/invite @Leads Classifier
```

> The bot only receives messages from channels it's invited to.

---

## CLI Commands

```bash
leads-agent init                    # Setup wizard
leads-agent config                  # Show configuration
leads-agent run [--reload]          # Start API server

# Classification
leads-agent classify "message"      # Classify a single message
leads-agent classify "msg" --enrich # Research promising leads

# Backtesting
leads-agent backtest --limit 20                    # Test on historical leads
leads-agent backtest --enrich                      # Include web research
leads-agent backtest --debug                       # Show agent steps
leads-agent backtest --enrich --debug --verbose    # Full trace

# Debugging
leads-agent pull-history --limit 10 --print        # View raw Slack messages
```

### Enrichment Options

When `--enrich` is enabled, promising leads are researched via web search:

| Option | Description |
|--------|-------------|
| `--enrich`, `-e` | Enable web search for promising leads |
| `--max-searches` | Limit searches per lead (default: 4) |
| `--debug`, `-d` | Show agent steps and token usage |
| `--verbose`, `-v` | Show full message history |

**What gets researched:**
- Company website and description (via email domain search)
- Industry and company size
- Contact's role/title

---

## LLM Configuration

### OpenAI (Default)

```bash
export OPENAI_API_KEY="sk-..."
export LLM_MODEL_NAME="gpt-4o"  # optional, defaults to gpt-4o-mini
```

### Ollama (Local)

```bash
ollama serve
ollama pull llama3.1:8b

export LLM_BASE_URL="http://localhost:11434/v1"
export LLM_MODEL_NAME="llama3.1:8b"
```

### Other Providers

Any OpenAI-compatible API works — set `LLM_BASE_URL`, `LLM_MODEL_NAME`, and `OPENAI_API_KEY`.

---

## Project Structure

```
leads-agent/
├── src/leads_agent/
│   ├── api.py        # FastAPI webhook handler
│   ├── cli.py        # Typer CLI
│   ├── config.py     # Settings (pydantic-settings)
│   ├── models.py     # HubSpotLead, LeadClassification, research models
│   ├── llm.py        # Classification + research agents
│   ├── backtest.py   # Historical lead testing
│   └── slack.py      # Slack client & signature verification
├── docs/ARCHITECTURE.md
├── slack-app-manifest.yml
└── pyproject.toml
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Invalid request" on Slack events | Check `SLACK_SIGNING_SECRET`; ensure server clock is synced |
| No classifications happening | Verify bot is invited to channel; check HubSpot is posting |
| Backtest shows no leads | Run `pull-history --print` to verify HubSpot messages exist |
| LLM errors | Check `OPENAI_API_KEY`; for Ollama ensure server is running |

---

## Documentation

- **[Architecture Guide](docs/ARCHITECTURE.md)** — Data flow, Slack manifest, classification system, deployment

## License

MIT — See [LICENSE](LICENSE)
