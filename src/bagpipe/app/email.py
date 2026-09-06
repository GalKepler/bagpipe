"""Email delivery — DESIGN.md §6 ("... emailed"). Plain `smtplib`/`email`
(stdlib) — no SMTP client dependency needed for send-and-attach-one-PDF.

`smtp_user`/`smtp_password` in `app` config are optional: unset (the
internal-relay case) sends plain, no STARTTLS/login; set (e.g. a
transactional provider like Resend, see deploy/README.md) upgrades to
STARTTLS + AUTH LOGIN before sending.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger(__name__)


def build_success_email(
    to_addr: str,
    from_addr: str,
    pdf_path: Path,
    results_url: str | None = None,
) -> EmailMessage:
    """Result email. The PDF is an attachment, not the only copy — if it is
    missing or unreadable the mail still goes out with the results link, since
    an email that silently never arrives is worse than one without its
    attachment. (Before this guard, a missing PDF raised out of the queue task
    and, as a side effect, skipped the retention cleanup entirely.)
    """
    msg = EmailMessage()
    msg["Subject"] = "Your Brain Age Gap report"
    msg["From"] = from_addr
    msg["To"] = to_addr

    body = ["Your uploaded scan has been processed."]
    if results_url:
        body.append(f"View your interactive results: {results_url}")

    try:
        pdf_bytes = pdf_path.read_bytes()
    except OSError:
        logger.exception("could not read report PDF at %s — sending email without it", pdf_path)
        body.append(
            "We couldn't attach your PDF report to this email, but your results "
            "are available at the link above."
            if results_url
            else "We couldn't attach your PDF report to this email. Please contact us."
        )
        msg.set_content("\n\n".join(body))
        return msg

    body.append("Your Brain Age Gap report is attached as a PDF.")
    msg.set_content("\n\n".join(body))
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename="bag_report.pdf")
    return msg


def build_failure_email(
    to_addr: str,
    from_addr: str,
    user_message: str,
    *,
    retained: bool = False,
) -> EmailMessage:
    """`retained` must reflect the uploader's actual per-upload consent — this
    mail makes a privacy claim, and asserting "nothing was retained" to someone
    who opted INTO retention would be a false statement, not just sloppy copy.
    """
    msg = EmailMessage()
    msg["Subject"] = "We couldn't process your Brain Age Gap upload"
    msg["From"] = from_addr
    msg["To"] = to_addr
    tail = (
        "You asked us to keep your uploaded scan, so it has been retained."
        if retained
        else "No further data was retained from this upload."
    )
    msg.set_content(f"{user_message}\n\n{tail}")
    return msg


def send(
    msg: EmailMessage,
    smtp_host: str | None,
    smtp_port: int,
    smtp_user: str | None = None,
    smtp_password: str | None = None,
) -> bool:
    """Sends `msg`. Returns False (and logs) if `smtp_host` isn't configured,
    rather than raising — a missing/misconfigured mail relay must never fail
    the job whose result it's trying to deliver.
    """
    if not smtp_host:
        logger.warning("app.smtp_host not configured — skipping email to %s", msg["To"])
        return False
    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            if smtp_user:
                server.starttls()
                server.login(smtp_user, smtp_password or "")
            server.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException):
        logger.exception("failed to send email to %s", msg["To"])
        return False
