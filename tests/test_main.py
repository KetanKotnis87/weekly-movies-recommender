"""
Tests for src/main.py (pipeline orchestration)

Covers: UC-001, UC-015

Tests the Saturday gate, --force flag, --dry-run flag,
sentinel file idempotency, and fatal error handling.

All external dependencies (TMDB, OMDb, SMTP, PDF generation) are mocked.
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from src.main import (
    _already_sent,
    _mark_sent,
    _sentinel_path,
    run_pipeline,
)


# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------


def _make_content_item(
    tmdb_id: int,
    title: str,
    language: str = "en",
    genre: str = "Action",
):
    """Create a minimal ContentItem for pipeline mock returns."""
    from datetime import timedelta
    from src.scorer import ContentItem, score_item

    item = ContentItem(
        id=tmdb_id,
        title=title,
        media_type="movie",
        genres=[genre],
        language=language,
        release_date=(date.today() - timedelta(days=100)).strftime("%Y-%m-%d"),
        tmdb_popularity=100.0,
        imdb_rating=7.5,
        vote_count=5000,
        overview="A test film.",
        poster_path="/test.jpg",
        ott_platforms=["Netflix"],
    )
    item.score = score_item(item)
    return item


def _make_mock_recommendations():
    """Return a minimal recommendations dict for pipeline tests."""
    item = _make_content_item(1, "Test Movie")
    return {
        "movies": {"Action": [item]},
        "series": {},
    }


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Set all required env vars so Config() initializes successfully."""
    monkeypatch.setenv("TMDB_API_KEY", "fake_tmdb_key")
    monkeypatch.setenv("OMDB_API_KEY", "fake_omdb_key")
    monkeypatch.setenv("GMAIL_ADDRESS", "test@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "testapppass")
    monkeypatch.setenv("RECIPIENT_EMAIL", "recipient@example.com")


@pytest.fixture
def patch_full_pipeline(tmp_path, mock_env_vars):
    """
    Comprehensive mock fixture that patches all external calls in run_pipeline().

    Returns a dict of mock objects for individual assertion.
    """
    item = _make_content_item(1, "Test Movie")
    recs = {"movies": {"Action": [item]}, "series": {}}

    from src.data_fetcher import RawMovie, RawTVSeries
    recent_date = (date.today() - timedelta(days=100)).strftime("%Y-%m-%d")

    raw_movie = RawMovie(
        id=1,
        title="Test Movie",
        original_language="en",
        spoken_languages=["en"],
        genre_ids=[28],
        release_date=recent_date,
        popularity=100.0,
        overview="A test movie.",
        poster_path="/test.jpg",
        imdb_id="tt1234567",
        imdb_rating=7.5,
        imdb_vote_count=5000,
        ott_platforms=["Netflix"],
    )

    mocks = {}

    with patch("src.main.TMDBClient") as mock_tmdb_cls, \
         patch("src.main.OMDbClient") as mock_omdb_cls, \
         patch("src.main.GoogleTrendsFetcher") as mock_trends_cls, \
         patch("src.main.YouTubeFetcher") as mock_yt_cls, \
         patch("src.main.generate_pdf") as mock_generate_pdf, \
         patch("src.main.send_report") as mock_send_report, \
         patch("src.main.setup_logging") as mock_setup_logging, \
         patch("src.main.rotate_logs") as mock_rotate_logs, \
         patch("src.main.LOG_DIR", tmp_path / "logs"), \
         patch("src.main.PROJECT_ROOT", tmp_path):

        # Configure TMDB client mock
        mock_tmdb = MagicMock()
        mock_tmdb.fetch_trending_movies.return_value = [raw_movie]
        mock_tmdb.fetch_trending_tv.return_value = []
        mock_tmdb.get_movie_external_ids.return_value = "tt1234567"
        mock_tmdb.get_tv_external_ids.return_value = None
        mock_tmdb.get_movie_watch_providers.return_value = ["Netflix"]
        mock_tmdb.get_tv_watch_providers.return_value = []
        mock_tmdb.download_poster.return_value = None
        mock_tmdb.call_count = 10
        mock_tmdb_cls.return_value = mock_tmdb

        # Configure OMDb client mock
        mock_omdb = MagicMock()
        mock_omdb.fetch_ratings.return_value = (7.5, 5000)
        mock_omdb_cls.return_value = mock_omdb

        # Configure GoogleTrendsFetcher mock — returns None (no real network calls)
        mock_trends = MagicMock()
        mock_trends.get_interest.return_value = None
        mock_trends_cls.return_value = mock_trends

        # Configure YouTubeFetcher mock — not used (no YOUTUBE_API_KEY in test env)
        mock_yt = MagicMock()
        mock_yt.get_trailer_views.return_value = None
        mock_yt_cls.return_value = mock_yt

        # Configure PDF generation mock — creates an actual file
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        def create_fake_pdf(recs, path, run_date=None):
            Path(path).write_bytes(b"%PDF-1.4\n%test\n%%EOF")
            return path

        mock_generate_pdf.side_effect = create_fake_pdf
        mock_setup_logging.return_value = MagicMock()

        mocks = {
            "tmdb": mock_tmdb,
            "omdb": mock_omdb,
            "trends": mock_trends,
            "yt": mock_yt,
            "generate_pdf": mock_generate_pdf,
            "send_report": mock_send_report,
            "rotate_logs": mock_rotate_logs,
        }

        yield mocks


# ---------------------------------------------------------------------------
# UC-001: Saturday gate
# ---------------------------------------------------------------------------


class TestSaturdayGate:
    """Tests for the Saturday scheduling gate (UC-001)."""

    def test_saturday_gate_allows_pipeline_to_proceed(self, patch_full_pipeline, tmp_path, monkeypatch):
        """weekday=5 (Saturday) allows the pipeline to proceed (UC-001 AC-1)."""
        saturday = date(2026, 3, 7)  # A Saturday (weekday=5)

        with patch("src.main.date") as mock_date, \
             patch("src.main.LOG_DIR", tmp_path / "logs"), \
             patch("src.main.PROJECT_ROOT", tmp_path):
            mock_date.today.return_value = saturday
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

            exit_code = run_pipeline(dry_run=True, force=False)

        assert exit_code == 0

    def test_monday_gate_exits_with_code_0_no_force(self, patch_full_pipeline, tmp_path, mock_env_vars):
        """weekday=0 (Monday) exits with code 0 without --force (UC-001 AC-2)."""
        monday = date(2026, 3, 2)  # A Monday (weekday=0)

        with patch("src.main.date") as mock_date, \
             patch("src.main.LOG_DIR", tmp_path / "logs"), \
             patch("src.main.PROJECT_ROOT", tmp_path):
            mock_date.today.return_value = monday
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

            exit_code = run_pipeline(dry_run=False, force=False)

        assert exit_code == 0
        # Email should NOT have been sent
        assert not patch_full_pipeline["send_report"].called

    def test_weekday_gate_exits_without_api_calls(self, mock_env_vars, tmp_path):
        """On non-Saturday without --force, no API calls are made (UC-001 AC-2)."""
        monday = date(2026, 3, 2)

        with patch("src.main.date") as mock_date, \
             patch("src.main.TMDBClient") as mock_tmdb_cls, \
             patch("src.main.OMDbClient") as mock_omdb_cls, \
             patch("src.main.setup_logging") as mock_logging, \
             patch("src.main.rotate_logs"), \
             patch("src.main.LOG_DIR", tmp_path / "logs"), \
             patch("src.main.PROJECT_ROOT", tmp_path):
            mock_date.today.return_value = monday
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            mock_logging.return_value = MagicMock()

            exit_code = run_pipeline(dry_run=False, force=False)

        assert exit_code == 0
        # TMDBClient should not have been instantiated
        assert not mock_tmdb_cls.called

    def test_non_saturday_various_weekdays_exit_cleanly(self, mock_env_vars, tmp_path):
        """All non-Saturday days (Mon-Fri, Sun) exit with code 0 (UC-001 AC-2)."""
        # Monday through Friday + Sunday
        non_saturdays = [
            date(2026, 3, 2),  # Monday
            date(2026, 3, 3),  # Tuesday
            date(2026, 3, 4),  # Wednesday
            date(2026, 3, 5),  # Thursday
            date(2026, 3, 6),  # Friday
            date(2026, 3, 8),  # Sunday
        ]

        for non_saturday in non_saturdays:
            with patch("src.main.date") as mock_date, \
                 patch("src.main.setup_logging") as mock_logging, \
                 patch("src.main.rotate_logs"), \
                 patch("src.main.LOG_DIR", tmp_path / "logs"), \
                 patch("src.main.PROJECT_ROOT", tmp_path):
                mock_date.today.return_value = non_saturday
                mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                mock_logging.return_value = MagicMock()

                exit_code = run_pipeline(dry_run=False, force=False)

            assert exit_code == 0, f"Expected exit 0 for {non_saturday.strftime('%A')}, got {exit_code}"


# ---------------------------------------------------------------------------
# UC-001: --force flag
# ---------------------------------------------------------------------------


class TestForceFlag:
    """Tests for the --force flag behavior (UC-001 AF-3)."""

    def test_force_flag_bypasses_saturday_gate_on_monday(self, patch_full_pipeline, tmp_path, mock_env_vars):
        """--force flag allows pipeline to run on Monday (UC-001 AF-3)."""
        monday = date(2026, 3, 2)

        with patch("src.main.date") as mock_date, \
             patch("src.main.LOG_DIR", tmp_path / "logs"), \
             patch("src.main.PROJECT_ROOT", tmp_path):
            mock_date.today.return_value = monday
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

            exit_code = run_pipeline(dry_run=True, force=True)

        assert exit_code == 0
        # Pipeline should have proceeded to PDF generation
        assert patch_full_pipeline["generate_pdf"].called

    def test_force_flag_bypasses_saturday_gate_on_sunday(self, patch_full_pipeline, tmp_path, mock_env_vars):
        """--force flag allows pipeline to run on Sunday."""
        sunday = date(2026, 3, 8)

        with patch("src.main.date") as mock_date, \
             patch("src.main.LOG_DIR", tmp_path / "logs"), \
             patch("src.main.PROJECT_ROOT", tmp_path):
            mock_date.today.return_value = sunday
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

            exit_code = run_pipeline(dry_run=True, force=True)

        assert exit_code == 0


# ---------------------------------------------------------------------------
# UC-001 / UC-013: --dry-run flag
# ---------------------------------------------------------------------------


class TestDryRunFlag:
    """Tests for the --dry-run flag behavior."""

    def test_dry_run_generates_pdf_but_does_not_call_email_sender(
        self, patch_full_pipeline, tmp_path, mock_env_vars
    ):
        """--dry-run flag runs pipeline and saves PDF, but skips email (UC-013)."""
        saturday = date(2026, 3, 7)

        with patch("src.main.date") as mock_date, \
             patch("src.main.LOG_DIR", tmp_path / "logs"), \
             patch("src.main.PROJECT_ROOT", tmp_path):
            mock_date.today.return_value = saturday
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

            exit_code = run_pipeline(dry_run=True, force=False)

        assert exit_code == 0
        # PDF should be generated
        assert patch_full_pipeline["generate_pdf"].called
        # Email should NOT be sent
        assert not patch_full_pipeline["send_report"].called

    def test_dry_run_does_not_write_sentinel_file(self, patch_full_pipeline, tmp_path, mock_env_vars):
        """--dry-run flag does not create a sentinel file (only real email sends create it)."""
        saturday = date(2026, 3, 7)
        sentinel = _sentinel_path(saturday)

        with patch("src.main.date") as mock_date, \
             patch("src.main.LOG_DIR", tmp_path / "logs"), \
             patch("src.main.PROJECT_ROOT", tmp_path):
            mock_date.today.return_value = saturday
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            mock_date.now = MagicMock(return_value=MagicMock())

            run_pipeline(dry_run=True, force=False)

        # Sentinel file should not exist in tmp_path
        # (since we patched LOG_DIR to tmp_path/logs, check there)
        sentinel_in_tmp = tmp_path / "logs" / f"sent_{saturday.isoformat()}.sentinel"
        assert not sentinel_in_tmp.exists()


# ---------------------------------------------------------------------------
# UC-001 / UC-013: Sentinel file idempotency
# ---------------------------------------------------------------------------


class TestSentinelFileIdempotency:
    """Tests for the sentinel file idempotency check (UC-001 AC-4, UC-013 AC-5)."""

    def test_second_run_on_same_saturday_is_skipped_due_to_sentinel(
        self, patch_full_pipeline, tmp_path, mock_env_vars
    ):
        """Second run on same Saturday is skipped if sentinel file exists (NFR-007)."""
        saturday = date(2026, 3, 7)

        # Create the sentinel file to simulate a previous successful run
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        sentinel_file = logs_dir / f"sent_{saturday.isoformat()}.sentinel"
        sentinel_file.write_text(f"Email sent at {saturday.isoformat()}\n", encoding="utf-8")

        with patch("src.main.date") as mock_date, \
             patch("src.main.LOG_DIR", logs_dir), \
             patch("src.main.PROJECT_ROOT", tmp_path):
            mock_date.today.return_value = saturday
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)

            exit_code = run_pipeline(dry_run=False, force=False)

        assert exit_code == 0
        # Email should NOT be sent again (idempotency)
        assert not patch_full_pipeline["send_report"].called

    def test_already_sent_returns_true_when_sentinel_exists(self, tmp_path, monkeypatch):
        """_already_sent() returns True when sentinel file exists."""
        run_date = date(2026, 3, 7)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # Patch LOG_DIR so _sentinel_path uses our temp directory
        with patch("src.main.LOG_DIR", logs_dir):
            sentinel = _sentinel_path(run_date)
            sentinel.write_text("sent\n", encoding="utf-8")
            assert _already_sent(run_date) is True

    def test_already_sent_returns_false_when_sentinel_missing(self, tmp_path):
        """_already_sent() returns False when sentinel file does not exist."""
        run_date = date(2026, 3, 7)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch("src.main.LOG_DIR", logs_dir):
            assert _already_sent(run_date) is False

    def test_mark_sent_creates_sentinel_file(self, tmp_path):
        """_mark_sent() creates a sentinel file at the expected path."""
        run_date = date(2026, 3, 7)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        with patch("src.main.LOG_DIR", logs_dir):
            _mark_sent(run_date)
            sentinel = _sentinel_path(run_date)
            assert sentinel.exists()


# ---------------------------------------------------------------------------
# UC-015: Fatal error handling
# ---------------------------------------------------------------------------


class TestFatalErrorHandling:
    """Tests for top-level fatal error handling."""

    def test_fatal_api_error_causes_exit_code_1(self, mock_env_vars, tmp_path):
        """FatalAPIError from TMDB causes exit code 1 (UC-015 AF-1, AC-3)."""
        from src.data_fetcher import FatalAPIError

        saturday = date(2026, 3, 7)

        with patch("src.main.date") as mock_date, \
             patch("src.main.TMDBClient") as mock_tmdb_cls, \
             patch("src.main.OMDbClient") as mock_omdb_cls, \
             patch("src.main.setup_logging") as mock_logging, \
             patch("src.main.rotate_logs"), \
             patch("src.main.LOG_DIR", tmp_path / "logs"), \
             patch("src.main.PROJECT_ROOT", tmp_path):
            mock_date.today.return_value = saturday
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            mock_logging.return_value = MagicMock()

            # Simulate TMDB returning FatalAPIError (401 Unauthorized)
            mock_tmdb = MagicMock()
            mock_tmdb.fetch_trending_movies.side_effect = FatalAPIError("[FATAL] HTTP 401")
            mock_tmdb_cls.return_value = mock_tmdb
            mock_omdb_cls.return_value = MagicMock()

            logs_dir = tmp_path / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)

            exit_code = run_pipeline(dry_run=True, force=False)

        assert exit_code == 1

    def test_missing_env_var_causes_exit_code_1(self, tmp_path, monkeypatch):
        """Missing required environment variable causes exit code 1 (UC-001 AF-2)."""
        # Remove all relevant env vars
        for var in ["TMDB_API_KEY", "OMDB_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "RECIPIENT_EMAIL"]:
            monkeypatch.delenv(var, raising=False)

        saturday = date(2026, 3, 7)

        with patch("src.main.date") as mock_date, \
             patch("src.main.setup_logging") as mock_logging, \
             patch("src.main.rotate_logs"), \
             patch("src.main.LOG_DIR", tmp_path / "logs"), \
             patch("src.main.PROJECT_ROOT", tmp_path):
            mock_date.today.return_value = saturday
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            mock_logging.return_value = MagicMock()

            logs_dir = tmp_path / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)

            exit_code = run_pipeline(dry_run=True, force=False)

        assert exit_code == 1

    def test_zero_tmdb_records_causes_exit_code_1(self, mock_env_vars, tmp_path):
        """Fetching 0 records from TMDB causes exit code 1 (pipeline cannot continue)."""
        saturday = date(2026, 3, 7)

        with patch("src.main.date") as mock_date, \
             patch("src.main.TMDBClient") as mock_tmdb_cls, \
             patch("src.main.OMDbClient") as mock_omdb_cls, \
             patch("src.main.setup_logging") as mock_logging, \
             patch("src.main.rotate_logs"), \
             patch("src.main.LOG_DIR", tmp_path / "logs"), \
             patch("src.main.PROJECT_ROOT", tmp_path):
            mock_date.today.return_value = saturday
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            mock_logging.return_value = MagicMock()

            mock_tmdb = MagicMock()
            mock_tmdb.fetch_trending_movies.return_value = []
            mock_tmdb.fetch_trending_tv.return_value = []
            mock_tmdb_cls.return_value = mock_tmdb
            mock_omdb_cls.return_value = MagicMock()

            logs_dir = tmp_path / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)

            exit_code = run_pipeline(dry_run=True, force=False)

        assert exit_code == 1

    def test_pdf_generation_failure_causes_exit_code_1(self, mock_env_vars, tmp_path):
        """PDF generation failure causes exit code 1 (UC-012 AF-4)."""
        from src.data_fetcher import RawMovie

        saturday = date(2026, 3, 7)
        recent_date = (date.today() - timedelta(days=100)).strftime("%Y-%m-%d")

        raw_movie = RawMovie(
            id=1,
            title="Test Movie",
            original_language="en",
            spoken_languages=["en"],
            genre_ids=[28],
            release_date=recent_date,
            popularity=100.0,
            overview="A test movie.",
            poster_path="/test.jpg",
            imdb_id="tt1234567",
            imdb_rating=7.5,
            imdb_vote_count=5000,
            ott_platforms=["Netflix"],
        )

        with patch("src.main.date") as mock_date, \
             patch("src.main.TMDBClient") as mock_tmdb_cls, \
             patch("src.main.OMDbClient") as mock_omdb_cls, \
             patch("src.main.GoogleTrendsFetcher") as mock_trends_cls, \
             patch("src.main.generate_pdf") as mock_generate_pdf, \
             patch("src.main.setup_logging") as mock_logging, \
             patch("src.main.rotate_logs"), \
             patch("src.main.LOG_DIR", tmp_path / "logs"), \
             patch("src.main.PROJECT_ROOT", tmp_path):
            mock_date.today.return_value = saturday
            mock_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
            mock_logging.return_value = MagicMock()

            mock_tmdb = MagicMock()
            mock_tmdb.fetch_trending_movies.return_value = [raw_movie]
            mock_tmdb.fetch_trending_tv.return_value = []
            mock_tmdb.get_movie_external_ids.return_value = "tt1234567"
            mock_tmdb.get_movie_watch_providers.return_value = ["Netflix"]
            mock_tmdb.download_poster.return_value = None
            mock_tmdb.call_count = 10
            mock_tmdb_cls.return_value = mock_tmdb

            mock_omdb = MagicMock()
            mock_omdb.fetch_ratings.return_value = (7.5, 5000)
            mock_omdb_cls.return_value = mock_omdb

            # Mock Google Trends fetcher to avoid real network calls
            mock_trends = MagicMock()
            mock_trends.get_interest.return_value = None
            mock_trends_cls.return_value = mock_trends

            # PDF generation raises an exception
            mock_generate_pdf.side_effect = Exception("PDF generation failed")

            logs_dir = tmp_path / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            output_dir = tmp_path / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            exit_code = run_pipeline(dry_run=True, force=False)

        assert exit_code == 1
