"""
Email sender module for the Weekly Movie & Web Series Recommender.

Sends the generated PDF as an attachment via Gmail SMTP (port 587, STARTTLS).
Credentials are loaded exclusively from environment variables.
"""

import logging
import smtplib
import time
from datetime import date
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List, Optional

from src.scorer import ContentItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GMAIL_HOST: str = "smtp.gmail.com"
GMAIL_PORT: int = 587


# ---------------------------------------------------------------------------
# EmailSender class
# ---------------------------------------------------------------------------


class EmailSender:
    """
    Sends the weekly watch-list PDF via Gmail SMTP with STARTTLS.

    Credentials (GMAIL_ADDRESS and GMAIL_APP_PASSWORD) are read from
    environment variables at construction time, not stored as class
    attributes beyond what is needed.
    """

    def __init__(self, gmail_address: str, gmail_app_password: str) -> None:
        """
        Initialise the sender with Gmail credentials.

        Args:
            gmail_address:      The sender's Gmail address.
            gmail_app_password: A 16-character Gmail App Password (not the
                                account password).
        """
        self._sender: str = gmail_address
        self._password: str = gmail_app_password

    def send(
        self,
        pdf_path: str,
        recipient_email: str,
        subject: str,
        week_date: date,
        recommendations: Optional[Dict[str, Dict[str, List[ContentItem]]]] = None,
    ) -> None:
        """
        Send the PDF report to the recipient.

        Args:
            pdf_path:         Absolute path to the PDF file to attach.
            recipient_email:  Destination email address.
            subject:          Email subject line.
            week_date:        The Saturday execution date (used for filename).
            recommendations:  Optional recommendations dict used to build the
                              plain-text body. If None, a generic body is used.

        Raises:
            FileNotFoundError: If the PDF does not exist at pdf_path.
            RuntimeError:      On SMTP connection or authentication failure.
        """
        # Guard: PDF must exist
        if not Path(pdf_path).is_file():
            msg = f"PDF file not found: {pdf_path}"
            logger.error("[EMAIL] FATAL — %s", msg)
            raise FileNotFoundError(msg)

        # Build message
        msg = self._build_message(
            pdf_path=pdf_path,
            recipient_email=recipient_email,
            subject=subject,
            week_date=week_date,
            recommendations=recommendations,
        )

        # Send via Gmail SMTP with 1 retry on transient connection failure.
        # SMTPAuthenticationError is not retried (permanent failure).
        _smtp_max_attempts = 2
        _smtp_retry_delay = 5  # seconds between connection retry attempts

        last_connect_exc: Optional[Exception] = None

        for _attempt in range(1, _smtp_max_attempts + 1):
            try:
                with smtplib.SMTP(GMAIL_HOST, GMAIL_PORT) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.ehlo()
                    smtp.login(self._sender, self._password)
                    smtp.sendmail(self._sender, recipient_email, msg.as_string())

                logger.info(
                    "[EMAIL] Email sent successfully to %s at %s.",
                    recipient_email,
                    date.today().isoformat(),
                )
                return  # Success — exit the retry loop

            except smtplib.SMTPAuthenticationError as exc:
                # Auth failure is permanent — do not retry
                logger.error(
                    "[EMAIL] FATAL — SMTP authentication failed. "
                    "Check GMAIL_ADDRESS and GMAIL_APP_PASSWORD.",
                )
                raise RuntimeError(
                    "SMTP authentication failed. "
                    "Verify your Gmail App Password is correct and 2FA is enabled."
                ) from exc

            except (smtplib.SMTPConnectError, OSError) as exc:
                last_connect_exc = exc
                if _attempt < _smtp_max_attempts:
                    logger.warning(
                        "[EMAIL] Connection attempt %d to %s:%d failed (%s). "
                        "Retrying in %ds.",
                        _attempt, GMAIL_HOST, GMAIL_PORT, type(exc).__name__, _smtp_retry_delay,
                    )
                    time.sleep(_smtp_retry_delay)
                else:
                    logger.error(
                        "[EMAIL] FATAL — Cannot connect to %s:%d after %d attempt(s).",
                        GMAIL_HOST, GMAIL_PORT, _smtp_max_attempts,
                    )
                    raise RuntimeError(
                        f"Cannot connect to {GMAIL_HOST}:{GMAIL_PORT} "
                        f"after {_smtp_max_attempts} attempt(s)."
                    ) from exc

            except smtplib.SMTPException as exc:
                logger.error("[EMAIL] SMTP error: %s", exc)
                raise RuntimeError(f"SMTP error during send: {exc}") from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_message(
        self,
        pdf_path: str,
        recipient_email: str,
        subject: str,
        week_date: date,
        recommendations: Optional[Dict[str, Dict[str, List[ContentItem]]]] = None,
    ) -> MIMEMultipart:
        """
        Construct the MIME multipart email message.

        Args:
            pdf_path:         Path to the PDF attachment.
            recipient_email:  Recipient email address.
            subject:          Subject line.
            week_date:        Execution date for attachment filename.
            recommendations:  Optional dict for generating the body summary.

        Returns:
            A fully constructed MIMEMultipart message object.
        """
        msg = MIMEMultipart()
        msg["From"] = self._sender
        msg["To"] = recipient_email
        msg["Subject"] = subject

        # Plain-text body
        body = self._build_body(week_date, recommendations)
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # PDF attachment
        attachment_filename = f"WeeklyWatchList_{week_date.strftime('%Y-%m-%d')}.pdf"
        try:
            with open(pdf_path, "rb") as fh:
                part = MIMEBase("application", "pdf")
                part.set_payload(fh.read())
        except OSError as exc:
            raise RuntimeError(
                f"Failed to read PDF attachment from '{pdf_path}': {exc}"
            ) from exc
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="{attachment_filename}"',
        )
        msg.attach(part)

        return msg

    @staticmethod
    def _build_body(
        week_date: date,
        recommendations: Optional[Dict[str, Dict[str, List[ContentItem]]]] = None,
    ) -> str:
        """
        Build the plain-text email body.

        Args:
            week_date:       The Saturday execution date.
            recommendations: Optional recommendations dict.

        Returns:
            Plain-text body string.
        """
        date_str = week_date.strftime("%d %B %Y")

        if recommendations is None:
            return (
                f"Hi,\n\n"
                f"Your weekly movie and web series recommendations for {date_str} "
                f"are attached as a PDF.\n\n"
                f"Enjoy your weekend watching!\n"
            )

        movie_recs = recommendations.get("movies", {})
        series_recs = recommendations.get("series", {})

        total_movies = sum(len(v) for v in movie_recs.values())
        total_series = sum(len(v) for v in series_recs.values())
        total = total_movies + total_series

        # Collect genres present in the report
        present_genres = []
        from src.config import GENRE_ORDER
        for genre in GENRE_ORDER:
            has_movies = bool(movie_recs.get(genre))
            has_series = bool(series_recs.get(genre))
            if has_movies or has_series:
                present_genres.append(genre)

        genres_str = ", ".join(present_genres) if present_genres else "N/A"

        lines = [
            "Hi,",
            "",
            f"Your weekly watch list for {date_str} is ready! "
            f"The attached PDF contains {total} curated picks across the following genres:",
            "",
            f"  Genres covered: {genres_str}",
            f"  Movies:     {total_movies} recommendation(s)",
            f"  Web Series: {total_series} recommendation(s)",
            "",
        ]

        # Per-genre breakdown
        for genre in GENRE_ORDER:
            genre_movies = movie_recs.get(genre, [])
            genre_series = series_recs.get(genre, [])
            if genre_movies or genre_series:
                lines.append(f"  {genre}:")
                for item in genre_movies:
                    rating = f"{item.imdb_rating:.1f}" if item.imdb_rating else "N/A"
                    lines.append(f"    [Movie]  {item.title} ({item.release_year}) — IMDB: {rating}")
                for item in genre_series:
                    rating = f"{item.imdb_rating:.1f}" if item.imdb_rating else "N/A"
                    lines.append(f"    [Series] {item.title} ({item.release_year}) — IMDB: {rating}")

        lines += [
            "",
            "Open the PDF for full details including poster images, OTT platforms, and plot teasers.",
            "",
            "Enjoy your weekend!",
        ]

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public convenience function
# ---------------------------------------------------------------------------


def send_report(
    pdf_path: str,
    gmail_address: str,
    gmail_app_password: str,
    recipient_email: str,
    week_date: date,
    recommendations: Optional[Dict[str, Dict[str, List[ContentItem]]]] = None,
) -> None:
    """
    Convenience wrapper: create an EmailSender and send the report.

    Args:
        pdf_path:             Path to the generated PDF.
        gmail_address:        Gmail sender address.
        gmail_app_password:   Gmail App Password.
        recipient_email:      Recipient email address.
        week_date:            The Saturday execution date.
        recommendations:      Optional recommendations dict for body generation.

    Raises:
        FileNotFoundError: If the PDF is missing.
        RuntimeError:      On SMTP failure.
    """
    date_str = week_date.strftime("%d %B %Y")
    subject = f"Your Weekly Movie & Series Picks \u2014 {date_str}"

    sender = EmailSender(gmail_address, gmail_app_password)
    sender.send(
        pdf_path=pdf_path,
        recipient_email=recipient_email,
        subject=subject,
        week_date=week_date,
        recommendations=recommendations,
    )
