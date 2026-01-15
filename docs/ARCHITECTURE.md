# Architecture Guide

How Leads Agent works — from lead submission to classification and enrichment.

---

## Overview

Leads Agent is a webhook service that:
1. Listens for HubSpot lead notifications in Slack
2. Parses contact info from the message
3. Classifies the lead using an LLM
4. Optionally researches promising leads via web search
5. Posts results as a threaded reply

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   HubSpot   │────▶│    Slack    │────▶│ Leads Agent  │────▶│   OpenAI    │
│  Workflow   │     │   Channel   │     │   (FastAPI)  │     │    LLM      │
└─────────────┘     └─────────────┘     └──────────────┘     └─────────────┘
     Form           Bot message         Filter & parse       Classify
   submission       with lead data      HubSpot messages     + research
```

---

## Components

| Component | File | Responsibility |
|-----------|------|----------------|
| **API** | `api.py` | Receives Slack webhooks, filters HubSpot messages, dispatches to classifier |
| **Models** | `models.py` | `HubSpotLead`, `LeadClassification`, `EnrichedLeadClassification`, research models |
| **Classifier** | `llm.py` | Classification agent + research agent with web search |
| **Slack** | `slack.py` | Slack SDK wrapper, HMAC signature verification |
| **Config** | `config.py` | Environment/`.env` settings via pydantic-settings |
| **CLI** | `cli.py` | Commands: `init`, `run`, `backtest`, `classify`, `pull-history` |
| **Backtest** | `backtest.py` | Historical lead testing |

---

## Data Flow

### 1. HubSpot → Slack

HubSpot posts leads to Slack via workflow automation:

```
New lead from Jane Smith
Company: Acme Corp
Email: jane@acme.com
Message: We need help with AWS migration...
```

### 2. Slack → Leads Agent

Slack sends an event to your webhook:

```json
{
  "type": "event_callback",
  "event": {
    "type": "message",
    "subtype": "bot_message",
    "username": "HubSpot",
    "attachments": [{
      "fallback": "*First Name*: Jane\n*Last Name*: Smith\n*Email*: jane@acme.com..."
    }]
  }
}
```

**Filtering logic:**
- Only `bot_message` subtype
- Only `username: "HubSpot"`
- Must have attachments

### 3. Classification

The lead is parsed into `HubSpotLead` and sent to the LLM:

```python
class LeadClassification(BaseModel):
    first_name: str | None
    last_name: str | None
    email: str | None
    company: str | None      # Extracted from message or email domain
    label: LeadLabel         # spam | solicitation | promising
    confidence: float        # 0.0–1.0
    reason: str
```

### 4. Web Search Enrichment (Optional)

For promising leads, a research agent performs web searches:

```python
class EnrichedLeadClassification(LeadClassification):
    company_research: CompanyResearch | None
    contact_research: ContactResearch | None
    research_summary: str | None

class CompanyResearch(BaseModel):
    company_name: str
    company_description: str
    industry: str | None
    company_size: str | None
    website: str | None

class ContactResearch(BaseModel):
    full_name: str
    title: str | None
    linkedin_summary: str | None
```

**Research strategy:**
1. Search email domain to find company website
2. Broader company search for description/industry
3. Search contact name + company for role

Uses pydantic-ai's built-in `duckduckgo_search_tool()` with configurable `max_searches` limit.

### 5. Response

If `DRY_RUN=false`, posts a threaded reply:

```
🟢 *PROMISING* (92%)
_Genuine infrastructure consulting inquiry_
📋 Company: Acme Corp
```

With enrichment:
```
🟢 *PROMISING* (92%)
_Genuine infrastructure consulting inquiry_

📊 Company Research:
   Acme Corp: Enterprise software for supply chain management
   Industry: SaaS / Logistics
   Website: acme.com

👤 Contact Research:
   Jane Smith - VP of Engineering
```

---

## Slack App Configuration

### Required Scopes

| Scope | Purpose |
|-------|---------|
| `channels:history` | Read public channel messages |
| `channels:read` | View public channel info |
| `groups:history` | Read private channel messages |
| `groups:read` | View private channel info |
| `chat:write` | Post replies |

### Event Subscriptions

- `message.channels` — Public channel messages
- `message.groups` — Private channel messages

> **Important:** Bot must be invited to channels to receive events.

### Request Verification

All requests are verified via HMAC-SHA256 signature:

```python
def verify_slack_request(settings, req, body):
    timestamp = req.headers.get("X-Slack-Request-Timestamp")
    signature = req.headers.get("X-Slack-Signature")
    
    # Reject requests older than 5 minutes
    if abs(time.time() - int(timestamp)) > 300:
        return False
    
    # Verify HMAC signature
    basestring = f"v0:{timestamp}:{body.decode()}"
    expected = "v0=" + hmac.new(
        signing_secret.encode(),
        basestring.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected, signature)
```

---

## Classification System

### Labels

| Label | Definition |
|-------|------------|
| 🟢 **promising** | Genuine service inquiry |
| 🟡 **solicitation** | Vendors, sales, recruiters |
| 🔴 **spam** | Junk, automated, irrelevant |

### System Prompt

```
You classify inbound leads from a consulting company contact form.

Classification labels:
- spam: irrelevant, automated, SEO/link-building, crypto, junk
- solicitation: vendors, sales pitches, recruiters, partnership offers
- promising: genuine inquiry about services or collaboration

Rules:
- Be conservative — if unclear, choose spam
- Extract the company name from the message or email domain if not provided
```

### Research Prompt

```
You are researching a promising sales lead.

You have access to DuckDuckGo search tool. Use it to research:
1. The COMPANY - search for the company website/domain first
2. The CONTACT PERSON - search for their name + company

Extract:
- What does the company do?
- What industry are they in?
- What is the contact's role/title?

Be efficient - limit your searches. Do NOT make up information.
```

---

## Backtesting

Test the classifier on historical leads before enabling live responses:

```bash
# Basic backtest
leads-agent backtest --limit 20

# With enrichment (researches promising leads)
leads-agent backtest --enrich --limit 10

# Debug mode (shows agent steps, tool calls)
leads-agent backtest --debug

# Full trace
leads-agent backtest --enrich --debug --verbose
```

**Sample output:**

```
[1] Processing lead...
    Input: Jane Smith <jane@acme.com>
    🔧 duckduckgo_search: {"query": "acme.com"}
    🔧 duckduckgo_search: {"query": "Jane Smith Acme Corp"}

Name: Jane Smith
Email: jane@acme.com
Message: We need help with AWS migration...

🟢 PROMISING (92%)
Reason: Genuine infrastructure consulting inquiry
Extracted Company: Acme Corp

📊 Company Research:
   Acme Corp: Enterprise logistics software
   Industry: SaaS
   Website: acme.com
```

---

## Deployment

### Local Development

```bash
# Terminal 1
leads-agent run --reload

# Terminal 2 (expose to internet)
ngrok http 8000
# or
tailscale funnel 8000
```

### Production

```bash
# Environment
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_CHANNEL_ID=C...
OPENAI_API_KEY=sk-...
DRY_RUN=false

# Run
leads-agent run --host 0.0.0.0 --port 8000
```

**Docker:**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install uv && uv pip install --system -e .
CMD ["leads-agent", "run", "--host", "0.0.0.0"]
```

### Security Checklist

- [ ] Signing secret configured and verified
- [ ] Bot token not exposed in logs
- [ ] HTTPS enforced
- [ ] DRY_RUN tested before enabling

---

## Flow Summary

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           LEADS AGENT FLOW                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  HubSpot → Slack Channel → POST /slack/events → LLM Classification      │
│                                                    │                    │
│                                                    ▼                    │
│                                         ┌─────────────────────┐         │
│                                         │  promising lead?    │         │
│                                         └─────────────────────┘         │
│                                            │              │             │
│                                           Yes            No             │
│                                            │              │             │
│                                            ▼              │             │
│                                    Web Search Research    │             │
│                                    (if --enrich)          │             │
│                                            │              │             │
│                                            ▼              ▼             │
│                                     Post threaded reply                 │
│                                     (if not DRY_RUN)                    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```
