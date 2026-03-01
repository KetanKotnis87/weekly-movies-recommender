"""
Tests for src/email_sender.py

Covers: UC-013

All SMTP connections are mocked — no real email is sent.
"""

import smtplib
from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

from src.email_sender import GMAIL_HOST, GMAIL_PORT, EmailSender, send_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_pdf_file(tmp_path, filename="test_report.pdf") -> str:
    """Create a minimal valid PDF file for attachment tests."""
    pdf_path = tmp_path / filename
    # Minimal PDF structure
    pdf_path.write_bytes(b"%PDF-1.4\n%test\n%%EOF")
    return str(pdf_path)


def _make_sender() -> EmailSender:
    """Create an EmailSender with test credentials."""
    return EmailSender(
        gmail_address="sender@gmail.com",
        gmail_app_password="testpassword123",
    )


# ---------------------------------------------------------------------------
# UC-013: SMTP connection setup
# ---------------------------------------------------------------------------


class TestEmailSenderSMTPSetup:
    """Tests for SMTP connection establishment."""

    def test_send_calls_smtp_with_correct_host_and_port(self, tmp_path):
        """send() calls smtplib.SMTP with correct host and port (UC-013 Main Flow step 3)."""
        pdf_path = _create_pdf_file(tmp_path)
        sender = _make_sender()

        with patch("src.email_sender.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            sender.send(
                pdf_path=pdf_path,
                recipient_email="recipient@example.com",
                subject="Test Subject",
                week_date=date(2026, 3, 7),
            )

        mock_smtp_cls.assert_called_once_with(GMAIL_HOST, GMAIL_PORT)
        assert GMAIL_HOST == "smtp.gmail.com"
        assert GMAIL_PORT == 587

    def test_send_calls_starttls(self, tmp_path):
        """send() calls starttls() to establish a secure connection (UC-013 Main Flow step 3)."""
        pdf_path = _create_pdf_file(tmp_path)
        sender = _make_sender()

        with patch("src.email_sender.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            sender.send(
                pdf_path=pdf_path,
                recipient_email="recipient@example.com",
                subject="Test Subject",
                week_date=date(2026, 3, 7),
            )

        mock_smtp.starttls.assert_called_once()

    def test_send_calls_login_with_correct_credentials(self, tmp_path):
        """send() calls login() with correct Gmail address and password (UC-013 step 4)."""
        pdf_path = _create_pdf_file(tmp_path)
        sender = EmailSender(
            gmail_address="mysender@gmail.com",
            gmail_app_password="myapppassword",
        )

        with patch("src.email_sender.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            sender.send(
                pdf_path=pdf_path,
                recipient_email="recipient@example.com",
                subject="Test Subject",
                week_date=date(2026, 3, 7),
            )

        mock_smtp.login.assert_called_once_with("mysender@gmail.com", "myapppassword")


# ---------------------------------------------------------------------------
# UC-013: PDF attachment
# ---------------------------------------------------------------------------


class TestEmailSenderAttachment:
    """Tests for PDF attachment in email."""

    def test_send_attaches_pdf_with_correct_filename_format(self, tmp_path):
        """PDF attachment filename follows 'WeeklyWatchList_YYYY-MM-DD.pdf' format (UC-013 AC-3)."""
        pdf_path = _create_pdf_file(tmp_path)
        sender = _make_sender()
        week_date = date(2026, 3, 7)

        with patch("src.email_sender.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            sender.send(
                pdf_path=pdf_path,
                recipient_email="recipient@example.com",
                subject="Test Subject",
                week_date=week_date,
            )

        # Check that sendmail was called — the message content includes the attachment filename
        assert mock_smtp.sendmail.called
        call_args = mock_smtp.sendmail.call_args
        message_string = call_args[0][2]  # Third argument is the message string
        expected_filename = f"WeeklyWatchList_{week_date.strftime('%Y-%m-%d')}.pdf"
        assert expected_filename in message_string

    def test_send_raises_file_not_found_if_pdf_missing(self, tmp_path):
        """send() raises FileNotFoundError if PDF file does not exist (UC-013 AF-4)."""
        sender = _make_sender()
        missing_path = str(tmp_path / "nonexistent.pdf")

        with pytest.raises(FileNotFoundError) as exc_info:
            sender.send(
                pdf_path=missing_path,
                recipient_email="recipient@example.com",
                subject="Test Subject",
                week_date=date(2026, 3, 7),
            )

        assert "not found" in str(exc_info.value).lower() or missing_path in str(exc_info.value)


# ---------------------------------------------------------------------------
# UC-013: Error handling
# ---------------------------------------------------------------------------


class TestEmailSenderErrorHandling:
    """Tests for SMTP error handling behavior."""

    def test_send_raises_runtime_error_on_smtp_auth_failure(self, tmp_path):
        """send() raises RuntimeError on SMTP authentication failure (UC-013 AF-1, AC-6)."""
        pdf_path = _create_pdf_file(tmp_path)
        sender = _make_sender()

        with patch("src.email_sender.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")

            with pytest.raises(RuntimeError) as exc_info:
                sender.send(
                    pdf_path=pdf_path,
                    recipient_email="recipient@example.com",
                    subject="Test Subject",
                    week_date=date(2026, 3, 7),
                )

        assert "authentication" in str(exc_info.value).lower() or "SMTP" in str(exc_info.value)

    def test_send_raises_runtime_error_on_smtp_connect_failure(self, tmp_path):
        """send() raises RuntimeError on SMTP connection failure (UC-013 AF-2)."""
        pdf_path = _create_pdf_file(tmp_path)
        sender = _make_sender()

        with patch("src.email_sender.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp_cls.side_effect = smtplib.SMTPConnectError(421, b"Cannot connect")

            with pytest.raises(RuntimeError):
                sender.send(
                    pdf_path=pdf_path,
                    recipient_email="recipient@example.com",
                    subject="Test Subject",
                    week_date=date(2026, 3, 7),
                )

    def test_send_raises_runtime_error_on_network_error(self, tmp_path):
        """send() raises RuntimeError on network OSError (UC-013 AF-2)."""
        pdf_path = _create_pdf_file(tmp_path)
        sender = _make_sender()

        with patch("src.email_sender.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp_cls.side_effect = OSError("Network unreachable")

            with pytest.raises(RuntimeError):
                sender.send(
                    pdf_path=pdf_path,
                    recipient_email="recipient@example.com",
                    subject="Test Subject",
                    week_date=date(2026, 3, 7),
                )


# ---------------------------------------------------------------------------
# UC-013: Subject format
# ---------------------------------------------------------------------------


class TestEmailSenderSubject:
    """Tests for email subject line format."""

    def test_send_subject_contains_formatted_date(self, tmp_path):
        """Email subject contains the properly formatted date (UC-013 AC-1).

        Note: The subject may be MIME-encoded (RFC 2047) when it contains non-ASCII
        characters such as the em-dash (U+2014). We decode the message before asserting.
        """
        import email as email_lib
        pdf_path = _create_pdf_file(tmp_path)
        sender = _make_sender()
        week_date = date(2026, 3, 7)
        expected_date_in_subject = "07 March 2026"
        subject = f"Your Weekly Movie & Series Picks \u2014 {expected_date_in_subject}"

        with patch("src.email_sender.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            sender.send(
                pdf_path=pdf_path,
                recipient_email="recipient@example.com",
                subject=subject,
                week_date=week_date,
            )

        assert mock_smtp.sendmail.called
        message_string = mock_smtp.sendmail.call_args[0][2]
        # Parse and decode the MIME message to check the subject
        parsed_msg = email_lib.message_from_string(message_string)
        decoded_subject = email_lib.header.decode_header(parsed_msg["Subject"])
        subject_text = "".join(
            part.decode(enc or "utf-8") if isinstance(part, bytes) else part
            for part, enc in decoded_subject
        )
        assert "07 March 2026" in subject_text

    def test_send_report_convenience_function_subject_format(self, tmp_path):
        """send_report() generates subject with correct date format (UC-013 AC-1).

        Note: The subject may be MIME-encoded (RFC 2047) when non-ASCII chars are present.
        We decode before asserting the date string is present.
        """
        import email as email_lib
        pdf_path = _create_pdf_file(tmp_path)
        week_date = date(2026, 3, 7)

        with patch("src.email_sender.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            send_report(
                pdf_path=pdf_path,
                gmail_address="sender@gmail.com",
                gmail_app_password="password",
                recipient_email="recipient@example.com",
                week_date=week_date,
            )

        assert mock_smtp.sendmail.called
        message_string = mock_smtp.sendmail.call_args[0][2]
        # Parse and decode the MIME message
        parsed_msg = email_lib.message_from_string(message_string)
        decoded_subject = email_lib.header.decode_header(parsed_msg["Subject"])
        subject_text = "".join(
            part.decode(enc or "utf-8") if isinstance(part, bytes) else part
            for part, enc in decoded_subject
        )
        assert "07 March 2026" in subject_text

    def test_send_report_subject_contains_em_dash(self, tmp_path):
        """Email subject uses em-dash character (—) in the date separator (UC-013 AC-1)."""
        pdf_path = _create_pdf_file(tmp_path)
        week_date = date(2026, 3, 7)

        with patch("src.email_sender.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            send_report(
                pdf_path=pdf_path,
                gmail_address="sender@gmail.com",
                gmail_app_password="password",
                recipient_email="recipient@example.com",
                week_date=week_date,
            )

        message_string = mock_smtp.sendmail.call_args[0][2]
        # The subject line should contain the em-dash
        assert "\u2014" in message_string or "&#8212" in message_string or "=E2=80=94" in message_string


# ---------------------------------------------------------------------------
# UC-013: send_report convenience wrapper
# ---------------------------------------------------------------------------


class TestSendReportWrapper:
    """Tests for the send_report public convenience function."""

    def test_send_report_calls_smtp_correctly(self, tmp_path):
        """send_report() delegates to EmailSender and sends via SMTP (UC-013)."""
        pdf_path = _create_pdf_file(tmp_path)

        with patch("src.email_sender.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            send_report(
                pdf_path=pdf_path,
                gmail_address="sender@gmail.com",
                gmail_app_password="apppassword",
                recipient_email="recipient@example.com",
                week_date=date(2026, 3, 7),
            )

        mock_smtp_cls.assert_called_once_with(GMAIL_HOST, GMAIL_PORT)
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once()
        mock_smtp.sendmail.assert_called_once()

    def test_send_report_raises_file_not_found_if_pdf_missing(self, tmp_path):
        """send_report() propagates FileNotFoundError if PDF is missing (UC-013)."""
        missing_path = str(tmp_path / "nonexistent.pdf")

        with pytest.raises(FileNotFoundError):
            send_report(
                pdf_path=missing_path,
                gmail_address="sender@gmail.com",
                gmail_app_password="apppassword",
                recipient_email="recipient@example.com",
                week_date=date(2026, 3, 7),
            )
