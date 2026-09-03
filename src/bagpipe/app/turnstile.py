"""Cloudflare Turnstile verification — anti-abuse gate for the public
`/predict` endpoint (see deploy/README.md § Public-abuse protection). Each
accepted upload costs ~an hour of the single GPU this app runs on, so an
unauthenticated, un-gated endpoint is a trivial DoS target; Turnstile keeps
out scripted submissions without putting a login wall in front of a public
health tool.

stdlib `urllib.request` — one POST per upload, not worth a new HTTP client
dependency (same reasoning as `bagpipe.app.email`).
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify(token: str, secret_key: str, remote_ip: str | None = None) -> bool:
    """Returns True iff Cloudflare accepts `token` as a solved challenge for
    `secret_key`. Fails closed (returns False) on any network/parse error —
    a Turnstile outage should not be treated as "skip the check".
    """
    data = {"secret": secret_key, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(_VERIFY_URL, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — fixed https URL
            result = json.loads(resp.read())
        return bool(result.get("success"))
    except (OSError, ValueError):
        logger.exception("turnstile verification request failed")
        return False
