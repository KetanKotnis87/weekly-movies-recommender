"""
Trends fetcher module for the Weekly Movie & Web Series Recommender — V2.

Provides:
- GoogleTrendsFetcher: queries pytrends for India-specific search interest (geo=IN).
- YouTubeFetcher: fetches trailer view counts via the YouTube Data API v3.

Both classes follow the same code style as OMDbClient in data_fetcher.py:
dataclasses, type hints, docstrings, logging, and graceful error handling.
All external I/O is wrapped in try/except; failures return None without
aborting the pipeline (NFR-009: graceful V1 fallback).
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    _GOOGLEAPI_AVAILABLE = True
except ImportError:
    _GOOGLEAPI_AVAILABLE = False
    HttpError = Exception  # fallback type alias


# ---------------------------------------------------------------------------
# Google Trends Fetcher
# ---------------------------------------------------------------------------


class GoogleTrendsFetcher:
    """
    Fetches 7-day India (geo=IN) Google Trends interest scores via pytrends.

    Each call queries "{title} {year}" for the past 7 days and returns the
    mean interest value (0–100).  A mandatory sleep of `sleep_seconds` is
    applied after every call to avoid triggering Google rate-limiting on the
    unofficial pytrends endpoint (FR-026).

    Failures (including TooManyRequestsError) are caught and logged at WARNING
    level; the method returns None so the pipeline can continue with a 0
    contribution for the Trends signal (NFR-009).
    """

    def __init__(self, sleep_seconds: float = 1.5) -> None:
        """
        Initialise the fetcher.

        Args:
            sleep_seconds: Seconds to sleep between successive pytrends calls.
                           Must be >= 1.5 to comply with FR-026.
        """
        from pytrends.request import TrendReq  # imported here so import errors are caught gracefully

        self._sleep_seconds = sleep_seconds
        self._pytrends = TrendReq(hl="en-US", tz=330)
        self._call_count: int = 0   # internal counter used for sleep-before logic
        self.call_count: int = 0
        self.success_count: int = 0
        self.failed_count: int = 0

    def get_interest(self, title: str, year: str) -> Optional[float]:
        """
        Return the mean 7-day Google Trends interest score (0–100) for India.

        Query string is "{title} {year}".  The DataFrame column is matched
        exactly against the query string; if the column is absent (pytrends
        disambiguation) the call is treated as a failure.

        Args:
            title: Display title of the movie or TV series.
            year:  4-digit release year as a string (e.g. '2025').

        Returns:
            Round float in [0.0, 100.0] on success, or None on any failure.
            None is treated as 0.0 in the scoring formula.
        """
        query = f"{title} {year}"

        # Sleep before the call (except the very first) to respect Google rate
        # limits (FR-026).  This produces exactly N-1 sleep intervals for N
        # calls (UC-016 AC-4).
        if self._call_count > 0:
            time.sleep(self._sleep_seconds)
        self._call_count += 1
        self.call_count += 1

        try:
            self._pytrends.build_payload([query], geo="IN", timeframe="now 7-d")
            df = self._pytrends.interest_over_time()

            if df is not None and not df.empty and query in df.columns:
                score = round(float(df[query].mean()), 1)
                logger.info("[TRENDS] %s → %.1f", query, score)
                self.success_count += 1
                return score

            # Empty DataFrame — no data for this title/timeframe
            logger.info("[TRENDS] %s → no data, defaulting to 0.", query)
            self.success_count += 1  # the call itself did not error
            return None

        except Exception as exc:
            exc_type = type(exc).__name__
            logger.warning(
                "[TRENDS] %s → FAILED (%s: %s), defaulting to 0.",
                query, exc_type, exc,
            )
            self.failed_count += 1
            return None

    def log_summary(self) -> None:
        """Log a summary of Google Trends call statistics."""
        logger.info(
            "[TRENDS] Summary: %d calls, %d succeeded, %d failed.",
            self.call_count, self.success_count, self.failed_count,
        )


# ---------------------------------------------------------------------------
# YouTube Fetcher
# ---------------------------------------------------------------------------


class YouTubeFetcher:
    """
    Fetches YouTube trailer view counts via the YouTube Data API v3.

    For each title the fetcher:
      1. Issues a search.list request for "{title} {year} official trailer".
      2. Takes the first result's videoId.
      3. Issues a videos.list request for viewCount statistics.

    On HTTP 403 quota exhaustion, sets quota_exhausted=True and skips all
    subsequent calls (UC-017 AF-3), logging a single WARNING.  All other
    exceptions are caught per-call and logged at WARNING level (FR-020,
    NFR-009).
    """

    def __init__(self, api_key: str) -> None:
        """
        Initialise the fetcher and build the YouTube API service object once.

        Building the service in __init__ avoids the overhead of reconstructing
        it on every call (HIGH-003).  If google-api-python-client is not
        installed or the build fails, quota_exhausted is set to True so all
        subsequent calls are skipped gracefully (HIGH-004, NFR-009).

        Args:
            api_key: A valid YouTube Data API v3 key (from Google Cloud Console).
        """
        self._api_key = api_key
        self.call_count: int = 0
        self.quota_exhausted: bool = False

        if not _GOOGLEAPI_AVAILABLE:
            logger.warning(
                "[YOUTUBE] google-api-python-client is not installed — "
                "YouTube enrichment disabled. Run: pip install google-api-python-client"
            )
            self._service = None
            self.quota_exhausted = True
            return

        try:
            self._service = build("youtube", "v3", developerKey=api_key)
        except Exception as exc:
            logger.warning("Failed to build YouTube API service: %s", exc)
            self._service = None
            self.quota_exhausted = True

    def get_trailer_views(self, title: str, year: str) -> Optional[int]:
        """
        Return the view count for the first YouTube official trailer result.

        Args:
            title: Display title of the movie or TV series.
            year:  4-digit release year as a string (e.g. '2025').

        Returns:
            Integer view count on success, or None if the trailer is not
            found, the quota is exhausted, or any error occurs.
            None is treated as 0 in the scoring formula.
        """
        if self.quota_exhausted or self._service is None:
            return None

        self.call_count += 1

        try:
            service = self._service

            # Step 1: search for the official trailer
            search_response = (
                service.search()
                .list(
                    q=f"{title} {year} official trailer",
                    part="id",
                    type="video",
                    maxResults=1,
                )
                .execute()
            )

            items = search_response.get("items", [])
            if not items:
                logger.info("[YOUTUBE] %s (%s) → no trailer found, defaulting to 0.", title, year)
                return None

            video_id = items[0]["id"]["videoId"]

            # Step 2: fetch view count statistics
            stats_response = (
                service.videos()
                .list(part="statistics", id=video_id)
                .execute()
            )

            stat_items = stats_response.get("items", [])
            if not stat_items:
                logger.info(
                    "[YOUTUBE] %s (%s) → video not found for ID %s, defaulting to 0.",
                    title, year, video_id,
                )
                return None

            view_count_raw = stat_items[0].get("statistics", {}).get("viewCount")
            if view_count_raw is None:
                logger.info(
                    "[YOUTUBE] %s (%s) → viewCount unavailable, defaulting to 0.", title, year,
                )
                return None

            views = int(view_count_raw)
            logger.info(
                "[YOUTUBE] %s (%s) → %d views (video ID: %s).", title, year, views, video_id,
            )
            return views

        except HttpError as exc:
            if exc.resp.status == 403:
                self.quota_exhausted = True
                logger.warning(
                    "[YOUTUBE] HTTP 403 — quota exhausted. "
                    "YouTube enrichment disabled for remaining titles."
                )
            else:
                logger.warning(
                    "[YOUTUBE] %s (%s) → HTTP %d error: %s",
                    title, year, exc.resp.status, exc,
                )
            return None

        except Exception as exc:
            logger.warning(
                "[YOUTUBE] %s (%s) → FAILED (%s: %s), defaulting to 0.",
                title, year, type(exc).__name__, exc,
            )
            return None

    def log_summary(self) -> None:
        """Log a summary of YouTube API call statistics."""
        logger.info(
            "[YOUTUBE] Summary: %d calls made. Quota exhausted: %s.",
            self.call_count, self.quota_exhausted,
        )
