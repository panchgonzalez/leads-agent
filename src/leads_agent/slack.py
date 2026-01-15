from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Request
from slack_sdk import WebClient

from .config import Settings


def slack_client(settings: Settings) -> WebClient:
    token = settings.slack_bot_token.get_secret_value() if settings.slack_bot_token else None
    return WebClient(token=token)


def verify_slack_request(settings: Settings, req: Request, body: bytes, debug: bool = True) -> bool:
    """
    Verify Slack request signature.

    Slack signs the *raw* request body. We use `body` bytes from FastAPI.
    """

    if settings.slack_signing_secret is None:
        if debug:
            print("  [VERIFY] FAILED: No signing secret configured")
        return False

    timestamp = req.headers.get("X-Slack-Request-Timestamp")
    signature = req.headers.get("X-Slack-Signature")

    if not timestamp or not signature:
        if debug:
            print(f"  [VERIFY] FAILED: Missing headers (timestamp={timestamp}, signature={signature})")
        return False

    try:
        ts = int(timestamp)
    except ValueError:
        if debug:
            print(f"  [VERIFY] FAILED: Invalid timestamp format: {timestamp}")
        return False

    time_diff = abs(time.time() - ts)
    if time_diff > 60 * 5:
        if debug:
            print(f"  [VERIFY] FAILED: Request too old ({time_diff:.0f}s)")
        return False

    basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected = (
        "v0="
        + hmac.new(
            settings.slack_signing_secret.get_secret_value().encode("utf-8"),
            basestring.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    )

    if not hmac.compare_digest(expected, signature):
        if debug:
            print("  [VERIFY] FAILED: Signature mismatch")
            print(f"    Expected: {expected[:30]}...")
            print(f"    Got:      {signature[:30]}...")
        return False

    return True
