"""Email delivery — DESIGN.md §6 ("... emailed"). Plain `smtplib`/`email`
(stdlib) — no SMTP client dependency needed for send-and-attach-one-PDF.

ponytail: no auth (user/password) in `app` config — `smtp_host`/`smtp_port`
assume an open internal relay, matching what's actually configured today
(`config/local.yaml`: all null, unset on this workstation). Add creds to
`app` config + `smtplib.SMTP.login()` here if/when a real relay needs them.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger(__name__)


def build_success_email(to_addr: str, from_addr: str, pdf_path: Path) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "Your Brain Age Gap report"
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(
        "Your uploaded scan has been processed. Your Brain Age Gap report is attached as a PDF."
    )
    msg.add_attachment(
        pdf_path.read_bytes(), maintype="application", subtype="pdf", filename="bag_report.pdf"
    )
    return msg


def build_failure_email(to_addr: str, from_addr: str, user_message: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "We couldn't process your Brain Age Gap upload"
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(f"{user_message}\n\nNo further data was retained from this upload.")
    return msg


def send(msg: EmailMessage, smtp_host: str | None, smtp_port: int) -> bool:
    """Sends `msg`. Returns False (and logs) if `smtp_host` isn't configured,
    rather than raising — a missing/misconfigured mail relay must never fail
    the job whose result it's trying to deliver.
    """
    if not smtp_host:
        logger.warning("app.smtp_host not configured — skipping email to %s", msg["To"])
        return False
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.send_message(msg)
        return True
    except OSError:
        logger.exception("failed to send email to %s", msg["To"])
        return False
