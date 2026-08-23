from pathlib import Path

from bagpipe.app import email as email_mod


def test_send_skips_gracefully_when_smtp_not_configured(caplog):
    msg = email_mod.build_failure_email("user@example.com", "noreply@bagpipe.local", "try again")
    sent = email_mod.send(msg, smtp_host=None, smtp_port=587)
    assert sent is False


def test_build_success_email_attaches_pdf(tmp_path: Path):
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n...")
    msg = email_mod.build_success_email("user@example.com", "noreply@bagpipe.local", pdf_path)
    attachments = list(msg.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "bag_report.pdf"
