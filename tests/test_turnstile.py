"""bagpipe.app.turnstile — Cloudflare Turnstile verification. Stubs
`urllib.request.urlopen` so this never makes a real network call.
"""

from __future__ import annotations

import io
import json

from bagpipe.app import turnstile


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_verify_true_on_success(monkeypatch):
    monkeypatch.setattr(
        turnstile.urllib.request,
        "urlopen",
        lambda req, timeout=10: _FakeResponse(json.dumps({"success": True}).encode()),
    )
    assert turnstile.verify("token", "secret") is True


def test_verify_false_on_rejection(monkeypatch):
    monkeypatch.setattr(
        turnstile.urllib.request,
        "urlopen",
        lambda req, timeout=10: _FakeResponse(
            json.dumps({"success": False, "error-codes": ["invalid-input-response"]}).encode()
        ),
    )
    assert turnstile.verify("bad-token", "secret") is False


def test_verify_false_on_network_error(monkeypatch):
    def _raise(req, timeout=10):
        raise OSError("boom")

    monkeypatch.setattr(turnstile.urllib.request, "urlopen", _raise)
    assert turnstile.verify("token", "secret") is False
