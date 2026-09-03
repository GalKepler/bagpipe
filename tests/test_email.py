from pathlib import Path
from unittest.mock import MagicMock

from bagpipe.app import email as email_mod


def test_send_skips_gracefully_when_smtp_not_configured(caplog):
    msg = email_mod.build_failure_email("user@example.com", "noreply@bagpipe.local", "try again")
    sent = email_mod.send(msg, smtp_host=None, smtp_port=587)
    assert sent is False


def test_send_authenticates_when_credentials_configured(monkeypatch):
    msg = email_mod.build_failure_email("user@example.com", "noreply@bagpipe.local", "try again")
    server = MagicMock()
    server.__enter__.return_value = server
    monkeypatch.setattr(email_mod.smtplib, "SMTP", lambda *a, **kw: server)

    sent = email_mod.send(
        msg, smtp_host="smtp.resend.com", smtp_port=587, smtp_user="resend", smtp_password="key"
    )

    assert sent is True
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("resend", "key")
    server.send_message.assert_called_once_with(msg)


def test_send_skips_auth_when_no_credentials(monkeypatch):
    msg = email_mod.build_failure_email("user@example.com", "noreply@bagpipe.local", "try again")
    server = MagicMock()
    server.__enter__.return_value = server
    monkeypatch.setattr(email_mod.smtplib, "SMTP", lambda *a, **kw: server)

    sent = email_mod.send(msg, smtp_host="localhost", smtp_port=25)

    assert sent is True
    server.starttls.assert_not_called()
    server.login.assert_not_called()


def test_build_success_email_attaches_pdf(tmp_path: Path):
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n...")
    msg = email_mod.build_success_email("user@example.com", "noreply@bagpipe.local", pdf_path)
    attachments = list(msg.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "bag_report.pdf"
