# Architecture & Integration Guide

This document explains how Leads Agent works, the data flow from lead submission to classification, and how to test the system.

---

## Table of Contents

- [Overview](#overview)
- [System Architecture](#system-architecture)
- [Data Flow](#data-flow)
  - [1. Lead Submission (HubSpot → Slack)](#1-lead-submission-hubspot--slack)
  - [2. Event Delivery (Slack → Leads Agent)](#2-event-delivery-slack--leads-agent)
  - [3. Classification (LLM)](#3-classification-llm)
  - [4. Response (Leads Agent → Slack)](#4-response-leads-agent--slack)
- [Slack App Configuration](#slack-app-configuration)
  - [Manifest Breakdown](#manifest-breakdown)
  - [OAuth Scopes Explained](#oauth-scopes-explained)
  - [Event Subscriptions](#event-subscriptions)
  - [Request Verification](#request-verification)
- [Classification System](#classification-system)
  - [Labels](#labels)
  - [LLM Prompt](#llm-prompt)
  - [Structured Output](#structured-output)
- [Backtesting](#backtesting)
  - [Purpose](#purpose)
  - [How It Works](#how-it-works)
  - [Interpreting Results](#interpreting-results)
- [Deployment Considerations](#deployment-considerations)

---

## Overview

Leads Agent is a webhook-based service that listens to a Slack channel for HubSpot lead notifications, parses the contact information, classifies the lead using an LLM, and posts the result as a threaded reply.

**Key Features:**
- **HubSpot-specific:** Only processes messages from the HubSpot bot (ignores other messages)
- **Contact extraction:** Parses first name, last name, email, company from HubSpot's message format
- **Smart classification:** Extracts company name from email domain if not provided
- **Threaded replies:** Posts classification as a thread reply to keep channels clean

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   HubSpot   │────▶│    Slack    │────▶│ Leads Agent  │────▶│   OpenAI    │
│  Workflow   │     │   Channel   │     │   (FastAPI)  │     │    LLM      │
│             │     │             │◀────│              │◀────│             │
└─────────────┘     └─────────────┘     └──────────────┘     └─────────────┘
     Form           Bot message         Filter HubSpot       Classify lead
   submission       with lead data      Parse contact info   Extract company
```

---

## System Architecture

```
leads-agent/
├── src/leads_agent/
│   ├── api.py          # FastAPI app — filters HubSpot messages, dispatches to classifier
│   ├── models.py       # Data models (HubSpotLead, LeadClassification)
│   ├── llm.py          # pydantic-ai agent for classification
│   ├── slack.py        # Slack SDK client & request verification
│   ├── config.py       # Environment-based settings (pydantic-settings)
│   ├── backtest.py     # Historical HubSpot lead testing
│   └── cli.py          # Typer CLI for setup/run/backtest/classify
└── slack-app-manifest.yml  # Slack App configuration template
```

### Key Components

| Component | Responsibility |
|-----------|----------------|
| **FastAPI (`api.py`)** | Receives Slack webhooks, filters for HubSpot messages only, parses leads, dispatches to classifier |
| **Models (`models.py`)** | `HubSpotLead` for parsing Slack events; `LeadClassification` for LLM output with contact info |
| **Classifier (`llm.py`)** | pydantic-ai Agent that classifies leads and extracts company name |
| **Slack Client (`slack.py`)** | Wraps `slack_sdk` for posting messages; implements HMAC signature verification |
| **Settings (`config.py`)** | Loads config from environment / `.env` using pydantic-settings |
| **CLI (`cli.py`)** | Typer-based CLI for `init`, `config`, `run`, `backtest`, `classify`, `pull-history` commands |

---

## Data Flow

### 1. Lead Submission (HubSpot → Slack)

When someone submits a contact form, HubSpot (or your CRM) posts a message to Slack.

**HubSpot Workflow Setup:**

1. In HubSpot, go to **Automation → Workflows**
2. Create a workflow triggered by "Form submission"
3. Add action: **Send Slack notification**
4. Configure the message template:

```
New lead from {{contact.firstname}} {{contact.lastname}}
Company: {{contact.company}}
Email: {{contact.email}}
Message: {{contact.message}}
```

5. Select your leads channel (the one Leads Agent monitors)

**What gets posted to Slack:**

```
New lead from Jane Smith
Company: Acme Corp
Email: jane@acme.com
Message: Hi, we're looking for help migrating our infrastructure to Kubernetes. 
We have about 50 microservices and need someone with AWS/EKS experience.
```

> **Note:** You can also use Zapier, Make, or direct Slack Incoming Webhooks from any form provider.

---

### 2. Event Delivery (Slack → Leads Agent)

When HubSpot posts a message to the channel, Slack sends an HTTP POST to your server.

**HubSpot Bot Message (Slack Event):**

```json
{
  "type": "event_callback",
  "event": {
    "type": "message",
    "subtype": "bot_message",
    "username": "HubSpot",
    "channel": "C0123456789",
    "ts": "1704067200.000001",
    "attachments": [{
      "fallback": "*First Name*: Jane\n*Last Name*: Smith\n*Email*: jane@acme.com\n*Message*: Hi, we need help with...",
      "text": "*First Name*: Jane\n*Last Name*: Smith\n..."
    }]
  }
}
```

**What Leads Agent does:**

```python
# api.py — simplified flow

def _is_hubspot_message(settings, event):
    """Only process HubSpot bot messages."""
    if event.get("subtype") != "bot_message":
        return False
    if event.get("username", "").lower() != "hubspot":
        return False
    if not event.get("attachments"):
        return False
    return True

@app.post("/slack/events")
async def slack_events(req: Request, background: BackgroundTasks):
    body = await req.body()
    
    # 1. Verify request is from Slack (HMAC signature)
    if not verify_slack_request(settings, req, body):
        return {"error": "Invalid request"}
    
    payload = await req.json()
    
    # 2. Handle Slack URL verification (one-time setup)
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}
    
    event = payload.get("event", {})
    
    # 3. Filter: only process HubSpot bot messages
    if _is_hubspot_message(settings, event):
        background.add_task(_handle_hubspot_lead, settings, event)
    
    return {"ok": True}
```

**Why filter for HubSpot only?**

- Prevents processing our own bot's replies (infinite loop)
- Ignores unrelated messages in the channel
- HubSpot has a specific message format we can reliably parse

**Why background processing?**

Slack expects a response within 3 seconds. LLM inference can take longer, so we:
1. Immediately return `{"ok": True}` to Slack
2. Process the classification in a background task
3. Post the reply asynchronously

---

### 3. Classification (LLM)

The parsed lead data is sent to an LLM with a structured output schema.

**Lead Parsing (HubSpot → HubSpotLead):**

```python
# models.py

class HubSpotLead(BaseModel):
    """Parsed lead data from HubSpot Slack message."""
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    company: str | None = None
    message: str | None = None
    raw_text: str = ""

    @classmethod
    def from_slack_event(cls, event: dict) -> HubSpotLead | None:
        """Parse HubSpot bot message from Slack event."""
        # Extract from attachments[0].fallback or .text
        # Parse fields like *First Name*: Value
        ...
```

**LLM Request:**

```python
# llm.py

SYSTEM_PROMPT = """
You classify inbound leads from a consulting company contact form.

Classification labels:
- spam: irrelevant, automated, SEO/link-building, crypto, junk
- solicitation: vendors, sales pitches, recruiters, partnership offers
- promising: genuine inquiry about services or collaboration

Rules:
- Be conservative — if unclear, choose spam
- Extract the company name from the message or email domain if not provided
- Provide a brief reason for your classification
"""

# Using pydantic-ai for structured output
agent = Agent(
    model=model,
    output_type=LeadClassification,  # Enforces JSON schema
    instructions=SYSTEM_PROMPT,
)

# Send formatted lead data
result = agent.run_sync(lead.to_prompt_text())
```

**LLM Response (structured):**

```json
{
  "first_name": "Jane",
  "last_name": "Smith",
  "email": "jane@acme.com",
  "company": "Acme Corp",
  "label": "promising",
  "confidence": 0.92,
  "reason": "Genuine infrastructure consulting inquiry with specific technical requirements"
}
```

**Structured Output with pydantic-ai:**

The `LeadClassification` model ensures the LLM returns valid JSON with contact info:

```python
# models.py

class LeadLabel(str, Enum):
    spam = "spam"
    solicitation = "solicitation"
    promising = "promising"

class LeadClassification(BaseModel):
    # Contact info (extracted/confirmed by LLM)
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    company: str | None = None  # Extracted from message or email domain

    # Classification
    label: LeadLabel
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
```

---

### 4. Response (Leads Agent → Slack)

If `DRY_RUN=false`, the bot posts a threaded reply:

```python
# api.py

label_emoji = {"spam": "🔴", "solicitation": "🟡", "promising": "🟢"}

response_parts = [
    f"{label_emoji[result.label.value]} *{result.label.value.upper()}* ({result.confidence:.0%})",
    f"_{result.reason}_",
]

# Add extracted company if different from parsed
if result.company and result.company != lead.company:
    response_parts.append(f"\n📋 Company: {result.company}")

client.chat_postMessage(
    channel=event["channel"],
    thread_ts=event["ts"],  # Reply in thread, not main channel
    text="\n".join(response_parts),
)
```

**What appears in Slack:**

```
┌──────────────────────────────────────────────────────────┐
│ 🚨 New Lead Alert!                                       │
│ Via strong.io                                            │
│ ┌─ HubSpot attachment ─────────────────────────────────┐ │
│ │ *First Name*: Jane                                   │ │
│ │ *Last Name*: Smith                                   │ │
│ │ *Email*: jane@acme.com                              │ │
│ │ *Message*: Hi, we're looking for help migrating...  │ │
│ └──────────────────────────────────────────────────────┘ │
│                                                          │
│ ┌─ Thread ────────────────────────────────────────────┐  │
│ │ 🟢 *PROMISING* (92%)                                │  │
│ │ _Genuine infrastructure consulting inquiry with     │  │
│ │ specific technical requirements_                    │  │
│ │ 📋 Company: Acme Corp                               │  │
│ └─────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

---

## Slack App Configuration

### Manifest Breakdown

The `slack-app-manifest.yml` declaratively configures your Slack App:

```yaml
display_information:
  name: Leads Classifier           # App name shown in Slack
  description: AI-powered lead classification bot
  background_color: "#1a1a2e"      # App icon background

features:
  bot_user:
    display_name: Leads Classifier # Bot username (@Leads Classifier)
    always_online: true            # Show green dot (cosmetic only)

oauth_config:
  scopes:
    bot:                           # Permissions the bot requests
      - channels:history           # Read messages in public channels (bot must be invited)
      - channels:read              # See public channel metadata
      - groups:history             # Read messages in private channels (bot must be invited)
      - groups:read                # See private channel metadata
      - chat:write                 # Post messages

settings:
  event_subscriptions:
    request_url: https://YOUR_DOMAIN/slack/events  # Your webhook URL
    bot_events:
      - message.channels           # Messages in public channels (bot must be member)
      - message.groups             # Messages in private channels (bot must be member)
```

> **Important:** The bot only receives messages from channels it's been invited to. This applies to both public and private channels. After installing the app, you must invite the bot to each channel where you want it to operate.

### OAuth Scopes Explained

| Scope | Why Needed |
|-------|------------|
| `channels:history` | Read messages in public channels the bot is invited to (required for backtesting + receiving events) |
| `channels:read` | Access basic public channel info (name, ID) — used by some SDK methods |
| `groups:history` | Read messages in private channels the bot is invited to |
| `groups:read` | Access basic private channel info (name, ID) |
| `chat:write` | Post messages as the bot (classification replies) |

> **Note:** The `groups:*` scopes are Slack's terminology for private channels. Despite the naming, this does not grant access to DMs or group DMs—only private channels where the bot is explicitly invited.

### Event Subscriptions

Slack uses a **push model** — when something happens, Slack POSTs to your URL.

```
┌─────────────┐         ┌──────────────────┐
│    Slack    │  POST   │   Your Server    │
│   Platform  │────────▶│ /slack/events    │
│             │         │                  │
│  (detects   │         │  (receives JSON  │
│   message)  │         │   event payload) │
└─────────────┘         └──────────────────┘
```

**URL Verification:**

When you first set the Request URL, Slack sends a challenge:

```json
{
  "type": "url_verification",
  "challenge": "abc123xyz"
}
```

Your server must respond:

```json
{
  "challenge": "abc123xyz"
}
```

This proves you control the endpoint.

### Request Verification

Every request from Slack is signed with your **Signing Secret**.

**Verification flow:**

```python
# slack.py

def verify_slack_request(settings, req, body):
    timestamp = req.headers.get("X-Slack-Request-Timestamp")
    signature = req.headers.get("X-Slack-Signature")
    
    # 1. Reject old requests (replay attack prevention)
    if abs(time.time() - int(timestamp)) > 300:  # 5 minutes
        return False
    
    # 2. Compute expected signature
    basestring = f"v0:{timestamp}:{body.decode()}"
    expected = "v0=" + hmac.new(
        signing_secret.encode(),
        basestring.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # 3. Constant-time comparison (timing attack prevention)
    return hmac.compare_digest(expected, signature)
```

**Why this matters:**

Without verification, anyone could POST fake events to your endpoint and trigger classifications or extract information.

---

## Classification System

### Labels

| Label | Definition | Examples |
|-------|------------|----------|
| 🟢 **promising** | Genuine service inquiry or collaboration | "We need help with AWS migration", "Interested in consulting rates" |
| 🟡 **solicitation** | Vendors, sales, recruiters, partnerships | "We offer SEO services", "Partnership opportunity", "Open to new roles?" |
| 🔴 **spam** | Junk, automated, irrelevant | "Buy crypto now", "You've won!", random gibberish |

### LLM Prompt

The system prompt is intentionally brief and rule-based:

```
You classify inbound leads from a consulting company contact form.

You will receive lead information including name, email, and their message.
Extract and return the contact details along with your classification.

Classification labels:
- spam: irrelevant, automated, SEO/link-building, crypto, junk
- solicitation: vendors, sales pitches, recruiters, partnership offers
- promising: genuine inquiry about services or collaboration

Rules:
- Be conservative — if unclear, choose spam
- Extract the company name from the message or email domain if not provided
- Provide a brief reason for your classification
```

**Design decisions:**

1. **Conservative default:** Ambiguous messages → spam. Better to manually review than miss a solicitation.
2. **Company extraction:** LLM infers company from email domain (e.g., `@brownbear.com` → "Brown Bear") when not provided.
3. **Short reason:** Forces the model to be concise; reasons appear in Slack.
4. **No few-shot examples:** Keeps token count low; structured output handles formatting.

### Structured Output

Using `pydantic-ai` ensures the LLM returns valid, typed data including contact info:

```python
class LeadClassification(BaseModel):
    # Contact info (extracted/confirmed by LLM)
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    company: str | None = None    # Extracted from message or email domain

    # Classification
    label: LeadLabel              # Enum: spam | solicitation | promising
    confidence: float             # 0.0–1.0, validated by Pydantic
    reason: str                   # Short explanation
```

The agent automatically:
- Injects the JSON schema into the prompt
- Parses the response
- Validates against the schema
- Retries if the LLM returns invalid JSON

---

## Backtesting

### Purpose

Before enabling live responses (`DRY_RUN=false`), you should verify the classifier works well on your actual HubSpot leads.

Backtesting lets you:
1. **Evaluate accuracy** on historical data
2. **Tune the prompt** based on misclassifications
3. **Spot edge cases** (e.g., legitimate messages marked as spam)

### How It Works

```python
# backtest.py — simplified

def fetch_hubspot_leads(settings, limit=50):
    """Fetch only HubSpot bot messages from channel history."""
    client = slack_client(settings)
    resp = client.conversations_history(channel=settings.slack_channel_id, limit=limit)
    
    for msg in resp.get("messages", []):
        # Only process HubSpot bot messages
        if msg.get("subtype") != "bot_message":
            continue
        if msg.get("username", "").lower() != "hubspot":
            continue
        
        lead = HubSpotLead.from_slack_event(msg)
        if lead:
            yield msg, lead

def run_backtest(settings, limit=50):
    for msg, lead in fetch_hubspot_leads(settings, limit=limit):
        result = classify_lead(settings, lead)
        
        print("-" * 60)
        print(f"Name: {lead.first_name} {lead.last_name}")
        print(f"Email: {lead.email}")
        print(f"Message: {lead.message[:200]}...")
        print(f"→ {result.label.value} ({result.confidence:.0%})")
        print(f"Reason: {result.reason}")
        if result.company:
            print(f"Extracted Company: {result.company}")
```

**Running a backtest:**

```bash
leads-agent backtest --limit 20
```

**Sample output:**

```
Backtesting last 20 HubSpot leads

------------------------------------------------------------
Name: Nick Hall
Email: nick@hucktracks.com
Message: I'm looking to leverage computer vision to identify individuals on camera...
🟢 PROMISING (90%)
Reason: Genuine request for services related to computer vision
Extracted Company: Hucktracks

------------------------------------------------------------
Name: Mai Nguyen
Email: mai.seoadvisor@gmail.com
Message: Hi, I'm an Expert Link Builder. I have high-authority sites...
🔴 SPAM (90%)
Reason: SEO/link-building solicitation
Extracted Company: seoadvisor

------------------------------------------------------------
Name: Jacob Shenderovich
Email: jacob.shenderovich@brownbear.com
Message: Hello, I was hoping to get information on data ingestion pipelines...
🟢 PROMISING (90%)
Reason: Detailed inquiry about consulting services
Extracted Company: Brown Bear
```

### Debugging: Pull Channel History

To inspect raw Slack messages (useful for debugging parsing issues):

```bash
# Save to JSON file
leads-agent pull-history --limit 20 --output history.json

# Print to console
leads-agent pull-history --limit 5 --print
```

### Interpreting Results

| Scenario | Action |
|----------|--------|
| Promising lead marked as spam | Review prompt; may need to loosen criteria |
| Solicitation marked as promising | Review prompt; add vendor patterns to definitions |
| Low confidence (<0.7) | Message is ambiguous; consider manual review workflow |
| Consistent misclassifications | Add few-shot examples or fine-tune the model |

**Iterating on the prompt:**

1. Run backtest
2. Identify misclassifications
3. Adjust `SYSTEM_PROMPT` in `llm.py`
4. Re-run backtest
5. Repeat until satisfied

---

## Deployment Considerations

### Local Development

```bash
# Terminal 1: Start the server
leads-agent run --reload

# Terminal 2: Expose via ngrok
ngrok http 8000
# Copy the https://xxx.ngrok.io URL to Slack manifest
```

### Production

**Requirements:**
- HTTPS endpoint (Slack requires TLS)
- Public IP or domain
- Process manager (systemd, Docker, etc.)

**Example with Docker:**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install uv && uv pip install --system -e .
CMD ["leads-agent", "run", "--host", "0.0.0.0", "--port", "8000"]
```

**Environment variables in production:**

```bash
# Required — Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_CHANNEL_ID=C...

# Required — LLM (OpenAI by default)
OPENAI_API_KEY=sk-...
LLM_MODEL_NAME=gpt-4o-mini

# Optional — for Ollama or other OpenAI-compatible providers
# LLM_BASE_URL=http://localhost:11434/v1

# Enable responses
DRY_RUN=false
```

### Security Checklist

- [ ] Signing secret is set and requests are verified
- [ ] Bot token is not exposed in logs
- [ ] HTTPS is enforced
- [ ] Rate limiting is in place (consider adding to FastAPI)
- [ ] DRY_RUN tested before enabling live responses

---

## Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              LEADS AGENT FLOW                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │ HubSpot  │───▶│  Slack   │───▶│ Leads Agent  │───▶│ LLM (OpenAI/     │  │
│  │ Workflow │    │ Channel  │    │ POST /slack/ │    │ Ollama)          │  │
│  │          │    │          │◀───│ events       │◀───│                  │  │
│  └──────────┘    └──────────┘    └──────────────┘    └──────────────────┘  │
│       │               │                │                      │            │
│   Form submit    Bot message      Filter HubSpot         Classify          │
│                  with lead data   Parse contact info     Extract company   │
│                                         │                      │            │
│                                    Background task        Return JSON      │
│                                         │                      │            │
│                                    Post threaded      {first_name, email,  │
│                                    reply (if not       company, label,     │
│                                    DRY_RUN)            confidence, reason} │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  BACKTEST MODE: Fetch HubSpot leads → Parse → Classify → Print results     │
│  (No Slack posts, just console output for evaluation)                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

For setup instructions, see the main [README.md](../README.md).
