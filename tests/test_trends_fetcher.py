"""
Tests for src/trends_fetcher.py — V2 Cycle 1

Covers: UC-016 (GoogleTrendsFetcher), UC-017 (YouTubeFetcher), UC-020 (graceful degradation)

All external I/O is mocked; no real API calls are made.
"""

import logging
from unittest.mock import MagicMock, patch, call

import pandas as pd
import pytest
import requests.exceptions

from src.trends_fetcher import GoogleTrendsFetcher, YouTubeFetcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_interest_df(query: str, values: list) -> pd.DataFrame:
    """Build a minimal pytrends interest_over_time DataFrame."""
    return pd.DataFrame({query: values})


def _make_http_error(status: int) -> "HttpError":
    """Build a googleapiclient.errors.HttpError with the given HTTP status."""
    from googleapiclient.errors import HttpError
    mock_resp = MagicMock()
    mock_resp.status = status
    return HttpError(resp=mock_resp, content=b"error content")


# ---------------------------------------------------------------------------
# GoogleTrendsFetcher tests  (UC-016)
# ---------------------------------------------------------------------------


class TestGoogleTrendsFetcher:
    """Unit tests for GoogleTrendsFetcher.get_interest() — UC-016."""

    # ------------------------------------------------------------------
    # Fixture: a fetcher with pytrends mocked at import level
    # ------------------------------------------------------------------

    @pytest.fixture
    def mock_trend_req_cls(self):
        """
        Patch pytrends.request.TrendReq so GoogleTrendsFetcher.__init__
        never imports the real library.
        """
        with patch("src.trends_fetcher.GoogleTrendsFetcher.__init__") as mock_init:
            # We'll build the fetcher manually in each test to have full control.
            mock_init.return_value = None
            yield mock_init

    def _make_fetcher(self, mock_pytrends: MagicMock, sleep_seconds: float = 0.0) -> GoogleTrendsFetcher:
        """
        Construct a GoogleTrendsFetcher with its internals set directly,
        bypassing __init__ so we avoid importing pytrends.
        """
        fetcher = object.__new__(GoogleTrendsFetcher)
        fetcher._sleep_seconds = sleep_seconds
        fetcher._pytrends = mock_pytrends
        fetcher._call_count = 0   # internal counter for sleep-before logic (HIGH-002)
        fetcher.call_count = 0
        fetcher.success_count = 0
        fetcher.failed_count = 0
        return fetcher

    # ------------------------------------------------------------------
    # UC-016 AC-1: success path — float returned in [0, 100]
    # ------------------------------------------------------------------

    def test_get_interest_returns_float_on_success(self):
        """
        UC-016 AC-1: When pytrends returns a non-empty DataFrame with a column
        matching the query, get_interest() returns a float between 0 and 100.
        """
        query = "Inception 2025"
        df = _make_interest_df(query, [60, 72, 68, 75])

        mock_pytrends = MagicMock()
        mock_pytrends.interest_over_time.return_value = df

        with patch("time.sleep"):
            fetcher = self._make_fetcher(mock_pytrends)
            result = fetcher.get_interest("Inception", "2025")

        assert result is not None
        assert isinstance(result, float)
        assert 0.0 <= result <= 100.0

    # ------------------------------------------------------------------
    # UC-016 AC-2: empty DataFrame returns None
    # ------------------------------------------------------------------

    def test_get_interest_returns_none_on_empty_dataframe(self):
        """
        UC-016 AC-2: When interest_over_time() returns an empty DataFrame,
        get_interest() returns None (pipeline treats this as 0).
        """
        mock_pytrends = MagicMock()
        mock_pytrends.interest_over_time.return_value = pd.DataFrame()

        with patch("time.sleep"):
            fetcher = self._make_fetcher(mock_pytrends)
            result = fetcher.get_interest("UnknownTitle", "2025")

        assert result is None

    # ------------------------------------------------------------------
    # UC-016 AC-3 / AF-2: exception returns None without re-raising
    # ------------------------------------------------------------------

    def test_get_interest_returns_none_on_exception(self):
        """
        UC-016 AF-2: When interest_over_time() raises any Exception,
        get_interest() catches it and returns None (pipeline does not abort).
        """
        mock_pytrends = MagicMock()
        mock_pytrends.interest_over_time.side_effect = Exception("TooManyRequestsError")

        with patch("time.sleep"):
            fetcher = self._make_fetcher(mock_pytrends)
            # Must not raise
            result = fetcher.get_interest("Movie", "2025")

        assert result is None

    # ------------------------------------------------------------------
    # FR-026 / UC-016: sleep applied after EVERY call (including failures)
    # ------------------------------------------------------------------

    def test_get_interest_sleeps_between_calls(self):
        """
        UC-016 AC-4 / FR-026: time.sleep is called BEFORE each call except
        the very first, producing exactly N-1 sleep intervals for N calls.
        Two calls → sleep called exactly once (between call 1 and call 2).
        """
        query1 = "Film1 2025"
        query2 = "Film2 2025"

        mock_pytrends = MagicMock()
        # First call: success; second call: empty
        mock_pytrends.interest_over_time.side_effect = [
            _make_interest_df(query1, [50, 60]),
            pd.DataFrame(),
        ]

        with patch("time.sleep") as mock_sleep:
            fetcher = self._make_fetcher(mock_pytrends, sleep_seconds=1.5)
            fetcher.get_interest("Film1", "2025")
            fetcher.get_interest("Film2", "2025")

        # N-1 sleeps for N calls: 2 calls → exactly 1 sleep
        assert mock_sleep.call_count == 1
        mock_sleep.assert_called_with(1.5)

    # ------------------------------------------------------------------
    # UC-016 AF-2: warning logged on failure
    # ------------------------------------------------------------------

    def test_get_interest_logs_warning_on_failure(self, caplog):
        """
        UC-016 AF-2: When pytrends raises an exception, a WARNING-level
        log entry is emitted.
        """
        mock_pytrends = MagicMock()
        mock_pytrends.interest_over_time.side_effect = RuntimeError("Rate limited")

        with patch("time.sleep"):
            fetcher = self._make_fetcher(mock_pytrends)
            with caplog.at_level(logging.WARNING, logger="src.trends_fetcher"):
                fetcher.get_interest("SomeMovie", "2024")

        assert any("FAILED" in record.message or "TRENDS" in record.message
                   for record in caplog.records)

    # ------------------------------------------------------------------
    # Counter tracking
    # ------------------------------------------------------------------

    def test_get_interest_increments_call_count(self):
        """call_count increments on every invocation."""
        mock_pytrends = MagicMock()
        df = _make_interest_df("Film A 2025", [40, 55, 60])
        mock_pytrends.interest_over_time.return_value = df

        with patch("time.sleep"):
            fetcher = self._make_fetcher(mock_pytrends)
            fetcher.get_interest("Film A", "2025")
            fetcher.get_interest("Film A", "2025")

        assert fetcher.call_count == 2

    def test_get_interest_increments_failed_count_on_exception(self):
        """failed_count increments when an exception is raised."""
        mock_pytrends = MagicMock()
        mock_pytrends.interest_over_time.side_effect = Exception("boom")

        with patch("time.sleep"):
            fetcher = self._make_fetcher(mock_pytrends)
            fetcher.get_interest("Film", "2025")

        assert fetcher.failed_count == 1
        assert fetcher.success_count == 0

    def test_get_interest_increments_success_count_on_empty_df(self):
        """
        Empty DataFrame is NOT a failure (the call succeeded but returned no data).
        success_count increments even on empty DataFrame.
        """
        mock_pytrends = MagicMock()
        mock_pytrends.interest_over_time.return_value = pd.DataFrame()

        with patch("time.sleep"):
            fetcher = self._make_fetcher(mock_pytrends)
            fetcher.get_interest("Film", "2025")

        assert fetcher.success_count == 1
        assert fetcher.failed_count == 0

    # ------------------------------------------------------------------
    # UC-016 AF-4: multi-keyword / mismatched column → returns None
    # ------------------------------------------------------------------

    def test_get_interest_returns_none_when_query_column_absent(self):
        """
        UC-016 AF-4: If the DataFrame does not contain a column matching the
        query string exactly, get_interest() treats it as empty and returns None.
        """
        mock_pytrends = MagicMock()
        # Column header is different from the query string
        mock_pytrends.interest_over_time.return_value = pd.DataFrame({"other_keyword": [10, 20]})

        with patch("time.sleep"):
            fetcher = self._make_fetcher(mock_pytrends)
            result = fetcher.get_interest("Inception", "2025")

        assert result is None


# ---------------------------------------------------------------------------
# YouTubeFetcher tests  (UC-017)
# ---------------------------------------------------------------------------


class TestYouTubeFetcher:
    """Unit tests for YouTubeFetcher.get_trailer_views() — UC-017."""

    def _make_fetcher(self, mock_service=None) -> YouTubeFetcher:
        """
        Construct a YouTubeFetcher with its internals set directly, bypassing
        __init__ so we avoid making a real googleapiclient build() call.
        The service object built in __init__ (HIGH-003) is injected via
        mock_service; if None a generic MagicMock is used.
        """
        fetcher = object.__new__(YouTubeFetcher)
        fetcher._api_key = "FAKE_KEY_FOR_TESTS"
        fetcher.call_count = 0
        fetcher.quota_exhausted = False
        fetcher._service = mock_service if mock_service is not None else MagicMock()
        return fetcher

    def _mock_service(self, video_id: str = "vid123", view_count: str = "1234567"):
        """
        Return a MagicMock that simulates the googleapiclient service chain:
          service.search().list(...).execute() → search response
          service.videos().list(...).execute() → stats response
        """
        service = MagicMock()

        # search().list().execute()
        search_resp = {
            "items": [{"id": {"videoId": video_id}}]
        }
        service.search.return_value.list.return_value.execute.return_value = search_resp

        # videos().list().execute()
        stats_resp = {
            "items": [{"statistics": {"viewCount": view_count}}]
        }
        service.videos.return_value.list.return_value.execute.return_value = stats_resp

        return service

    # ------------------------------------------------------------------
    # UC-017 AC-1: success path
    # ------------------------------------------------------------------

    def test_get_trailer_views_returns_int_on_success(self):
        """
        UC-017 AC-1: search returns one video ID, stats return viewCount='1234567';
        get_trailer_views() returns the integer 1234567.
        """
        mock_service = self._mock_service(video_id="abc123", view_count="1234567")
        fetcher = self._make_fetcher(mock_service=mock_service)

        result = fetcher.get_trailer_views("Inception", "2025")

        assert result == 1234567
        assert isinstance(result, int)

    # ------------------------------------------------------------------
    # UC-017 AF-1: empty search results → None
    # ------------------------------------------------------------------

    def test_get_trailer_views_returns_none_on_empty_search(self):
        """
        UC-017 AF-1: When search.list returns an empty items array,
        get_trailer_views() returns None without raising.
        """
        mock_service = MagicMock()
        mock_service.search.return_value.list.return_value.execute.return_value = {"items": []}
        fetcher = self._make_fetcher(mock_service=mock_service)

        result = fetcher.get_trailer_views("Unknown Film", "2025")

        assert result is None

    # ------------------------------------------------------------------
    # UC-017 AF-3: HTTP 403 quota exhausted → None + quota_exhausted=True
    # ------------------------------------------------------------------

    def test_get_trailer_views_returns_none_on_http_403(self):
        """
        UC-017 AF-3: HTTP 403 sets quota_exhausted=True and returns None.
        """
        http_error = _make_http_error(403)
        mock_service = MagicMock()
        mock_service.search.return_value.list.return_value.execute.side_effect = http_error
        fetcher = self._make_fetcher(mock_service=mock_service)

        result = fetcher.get_trailer_views("Movie", "2025")

        assert result is None
        assert fetcher.quota_exhausted is True

    # ------------------------------------------------------------------
    # UC-017 AF-3: once quota_exhausted, no further API calls made
    # ------------------------------------------------------------------

    def test_get_trailer_views_skips_all_after_quota_exhausted(self):
        """
        UC-017 AF-3: If quota_exhausted is already True before the call,
        no API call is made and None is returned immediately.
        """
        mock_service = MagicMock()
        fetcher = self._make_fetcher(mock_service=mock_service)
        fetcher.quota_exhausted = True

        result = fetcher.get_trailer_views("Film", "2025")

        assert result is None
        # The service's search method should never have been called
        mock_service.search.assert_not_called()

    # ------------------------------------------------------------------
    # UC-017 AF-4: network-level exception → None (no raise)
    # ------------------------------------------------------------------

    def test_get_trailer_views_returns_none_on_network_error(self):
        """
        UC-017 AF-4: A network-level exception (e.g. requests.exceptions.RequestException)
        is caught; get_trailer_views() returns None without propagating.
        """
        mock_service = MagicMock()
        mock_service.search.return_value.list.return_value.execute.side_effect = (
            requests.exceptions.RequestException("Connection refused")
        )
        fetcher = self._make_fetcher(mock_service=mock_service)

        result = fetcher.get_trailer_views("Movie", "2025")

        assert result is None

    # ------------------------------------------------------------------
    # UC-017 AF-2: empty videos.list items → None
    # ------------------------------------------------------------------

    def test_get_trailer_views_returns_none_on_empty_stats_items(self):
        """
        UC-017 AF-2: When videos.list returns an empty items array (video
        no longer available), get_trailer_views() returns None.
        """
        mock_service = MagicMock()

        # search returns a video ID
        mock_service.search.return_value.list.return_value.execute.return_value = {
            "items": [{"id": {"videoId": "vid999"}}]
        }
        # but videos.list finds nothing
        mock_service.videos.return_value.list.return_value.execute.return_value = {"items": []}

        fetcher = self._make_fetcher(mock_service=mock_service)
        result = fetcher.get_trailer_views("GhostVideo", "2024")

        assert result is None

    # ------------------------------------------------------------------
    # UC-017 AF-5: viewCount absent from statistics → None
    # ------------------------------------------------------------------

    def test_get_trailer_views_returns_none_when_view_count_absent(self):
        """
        UC-017 AF-5: When viewCount is absent from the statistics dict
        (views hidden by channel), get_trailer_views() returns None.
        """
        mock_service = MagicMock()

        mock_service.search.return_value.list.return_value.execute.return_value = {
            "items": [{"id": {"videoId": "hiddenVid"}}]
        }
        mock_service.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"statistics": {}}]  # viewCount key absent
        }

        fetcher = self._make_fetcher(mock_service=mock_service)
        result = fetcher.get_trailer_views("PrivateChannel Film", "2024")

        assert result is None

    # ------------------------------------------------------------------
    # call_count increments
    # ------------------------------------------------------------------

    def test_get_trailer_views_increments_call_count(self):
        """call_count increments for each non-skipped invocation."""
        mock_service = self._mock_service()
        fetcher = self._make_fetcher(mock_service=mock_service)

        fetcher.get_trailer_views("Film A", "2025")
        fetcher.get_trailer_views("Film B", "2025")

        assert fetcher.call_count == 2

    def test_get_trailer_views_does_not_increment_count_when_quota_exhausted(self):
        """call_count does NOT increment when skipping due to quota exhaustion."""
        fetcher = self._make_fetcher()
        fetcher.quota_exhausted = True

        fetcher.get_trailer_views("Film", "2025")

        assert fetcher.call_count == 0

    # ------------------------------------------------------------------
    # Non-403 HttpError handled gracefully
    # ------------------------------------------------------------------

    def test_get_trailer_views_returns_none_on_non_403_http_error(self):
        """
        A non-403 HttpError (e.g. 500) is caught and None is returned.
        quota_exhausted remains False.
        """
        http_error = _make_http_error(500)
        mock_service = MagicMock()
        mock_service.search.return_value.list.return_value.execute.side_effect = http_error
        fetcher = self._make_fetcher(mock_service=mock_service)

        result = fetcher.get_trailer_views("Movie", "2025")

        assert result is None
        assert fetcher.quota_exhausted is False

    # ------------------------------------------------------------------
    # Warning logged on 403
    # ------------------------------------------------------------------

    def test_get_trailer_views_logs_warning_on_403(self, caplog):
        """
        UC-017 AF-3: HTTP 403 produces a WARNING-level log entry containing
        'quota exhausted'.
        """
        http_error = _make_http_error(403)
        mock_service = MagicMock()
        mock_service.search.return_value.list.return_value.execute.side_effect = http_error
        fetcher = self._make_fetcher(mock_service=mock_service)

        with caplog.at_level(logging.WARNING, logger="src.trends_fetcher"):
            fetcher.get_trailer_views("Movie", "2025")

        assert any(
            "quota" in record.message.lower() or "403" in record.message
            for record in caplog.records
        )
