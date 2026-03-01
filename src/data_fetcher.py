"""
Data fetcher module for the Weekly Movie & Web Series Recommender.

Provides:
- TMDBClient: fetches trending movies/TV, watch providers, external IDs,
  discover results, and poster images from the TMDB API.
- OMDbClient: fetches IMDB rating and vote count from the OMDb API.

Both clients implement exponential-backoff retry logic (max 3 retries,
delays 1 s / 2 s / 4 s) and raise immediately on HTTP 401.
"""

import logging
import time
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Dict, List, Optional

import requests
from PIL import Image

from src.config import (
    MAX_RETRIES,
    OMDB_BASE_URL,
    OMDB_RATE_LIMIT_WARN,
    OTT_NAME_ALIASES,
    PERMITTED_OTT_NAMES,
    RETRY_DELAYS,
    TMDB_BASE_URL,
    TMDB_IMAGE_BASE_URL,
    TMDB_MAX_PAGES,
    TMDB_RATE_LIMIT_WARN,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Typed data structures
# ---------------------------------------------------------------------------


@dataclass
class RawMovie:
    """Raw movie record from TMDB trending/discover responses."""

    id: int
    title: str
    original_language: str
    spoken_languages: List[str]     # list of iso_639_1 codes
    genre_ids: List[int]
    release_date: str               # YYYY-MM-DD or ""
    popularity: float
    overview: str
    poster_path: Optional[str]
    imdb_id: Optional[str] = None
    imdb_rating: Optional[float] = None
    imdb_vote_count: int = 0
    ott_platforms: List[str] = field(default_factory=list)
    poster_image: Optional[bytes] = None


@dataclass
class RawTVSeries:
    """Raw TV series record from TMDB trending/discover responses."""

    id: int
    title: str                      # from 'name' field
    original_language: str
    spoken_languages: List[str]
    genre_ids: List[int]
    first_air_date: str             # YYYY-MM-DD or ""
    popularity: float
    overview: str
    poster_path: Optional[str]
    imdb_id: Optional[str] = None
    imdb_rating: Optional[float] = None
    imdb_vote_count: int = 0
    ott_platforms: List[str] = field(default_factory=list)
    poster_image: Optional[bytes] = None


# ---------------------------------------------------------------------------
# Non-retriable error
# ---------------------------------------------------------------------------


class FatalAPIError(RuntimeError):
    """Raised immediately on HTTP 401; the pipeline must exit."""


# ---------------------------------------------------------------------------
# Helper: HTTP request with exponential backoff
# ---------------------------------------------------------------------------


def _request_with_retry(
    url: str,
    params: Dict[str, Any],
    call_label: str,
) -> Optional[Dict[str, Any]]:
    """
    Perform a GET request with up to MAX_RETRIES retries on 429 / 5xx.

    Args:
        url:        The fully-qualified endpoint URL.
        params:     Query-string parameters (dict).
        call_label: A short string identifying the call for log messages.

    Returns:
        Parsed JSON dict on success, or None if all retries are exhausted.

    Raises:
        FatalAPIError: Immediately on HTTP 401 (bad API key).
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, params=params, timeout=15)

            if response.status_code == 401:
                raise FatalAPIError(
                    f"[FATAL] HTTP 401 Unauthorized on {call_label} ({url}). "
                    f"Check your API key. Pipeline cannot continue."
                )

            if response.status_code in (400, 404):
                logger.error(
                    "[%s] HTTP %d (non-retriable) — skipping. URL: %s",
                    call_label, response.status_code, url,
                )
                return None

            if response.status_code == 200:
                try:
                    return response.json()
                except Exception as exc:
                    logger.error(
                        "[%s] Malformed JSON response: %s. Body (first 500 chars): %s",
                        call_label, exc, response.text[:500],
                    )
                    return None

            # Retriable: 429 or 5xx
            delay = RETRY_DELAYS[attempt - 1]
            if attempt < MAX_RETRIES:
                logger.warning(
                    "[%s] Attempt %d failed (HTTP %d). Retrying in %ds.",
                    call_label, attempt, response.status_code, delay,
                )
                time.sleep(delay)
            else:
                logger.warning(
                    "[%s] Attempt %d failed (HTTP %d). Waiting %ds before giving up.",
                    call_label, attempt, response.status_code, delay,
                )
                time.sleep(delay)
                logger.error(
                    "[%s] All %d attempts exhausted (HTTP %d). Giving up.",
                    call_label, MAX_RETRIES, response.status_code,
                )
                return None

        except FatalAPIError:
            raise
        except Exception as exc:
            delay = RETRY_DELAYS[attempt - 1]
            if attempt < MAX_RETRIES:
                logger.warning(
                    "[%s] Attempt %d failed (%s). Retrying in %ds.",
                    call_label, attempt, exc, delay,
                )
                time.sleep(delay)
            else:
                logger.warning(
                    "[%s] Attempt %d failed (%s). Waiting %ds before giving up.",
                    call_label, attempt, exc, delay,
                )
                time.sleep(delay)
                logger.error(
                    "[%s] All %d attempts exhausted (%s). Giving up.",
                    call_label, MAX_RETRIES, exc,
                )
                return None

    return None


# ---------------------------------------------------------------------------
# TMDB Client
# ---------------------------------------------------------------------------


class TMDBClient:
    """
    Client for the TMDB v3 API.

    All public methods log their call counts using the [TMDB_CALL] tag so
    that the operator can verify compliance with the 500-request budget.
    """

    def __init__(self, api_key: str) -> None:
        """
        Initialise the client.

        Args:
            api_key: A valid TMDB v3 API key.
        """
        self._api_key = api_key
        self._call_count: int = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, extra_params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Make a single authenticated GET request to the TMDB API.

        Args:
            path:         Endpoint path (e.g. '/trending/movie/week').
            extra_params: Additional query parameters to merge in.

        Returns:
            Parsed JSON dict or None on failure.
        """
        self._call_count += 1
        if self._call_count >= TMDB_RATE_LIMIT_WARN:
            logger.warning(
                "[TMDB_CALL] Approaching rate limit: %d calls made this run.",
                self._call_count,
            )
        logger.debug("[TMDB_CALL] #%d → %s", self._call_count, path)

        params: Dict[str, Any] = {"api_key": self._api_key}
        if extra_params:
            params.update(extra_params)

        url = f"{TMDB_BASE_URL}{path}"
        return _request_with_retry(url, params, f"TMDB{path}")

    def _extract_spoken_languages(self, record: Dict[str, Any]) -> List[str]:
        """Extract iso_639_1 codes from the spoken_languages array."""
        spoken = record.get("spoken_languages") or []
        return [lang.get("iso_639_1", "") for lang in spoken if lang.get("iso_639_1")]

    # ------------------------------------------------------------------
    # Trending endpoints
    # ------------------------------------------------------------------

    def fetch_trending_movies(self) -> List[RawMovie]:
        """
        Fetch trending movies for the current week (up to TMDB_MAX_PAGES pages).

        Returns:
            List of RawMovie objects. May be empty on failure.
        """
        movies: List[RawMovie] = []
        total_pages = 1

        for page in range(1, TMDB_MAX_PAGES + 1):
            if page > total_pages:
                break

            data = self._get("/trending/movie/week", {"page": page})
            if data is None:
                logger.error("[TMDB] trending/movie/week page %d returned None.", page)
                break

            total_pages = min(data.get("total_pages", 1), TMDB_MAX_PAGES)
            results = data.get("results", [])

            for record in results:
                movie_id = record.get("id")
                title = record.get("title") or record.get("original_title")
                if not movie_id or not title:
                    logger.debug("Discarding movie record missing id or title: %s", record)
                    continue

                movies.append(RawMovie(
                    id=int(movie_id),
                    title=str(title),
                    original_language=record.get("original_language", ""),
                    spoken_languages=self._extract_spoken_languages(record),
                    genre_ids=[int(g) for g in record.get("genre_ids", [])],
                    release_date=record.get("release_date", "") or "",
                    popularity=float(record.get("popularity", 0.0) or 0.0),
                    overview=record.get("overview", "") or "",
                    poster_path=record.get("poster_path"),
                ))

        logger.info("[TMDB] Fetched %d raw movie records (%d TMDB calls so far).", len(movies), self._call_count)
        return movies

    def fetch_trending_tv(self) -> List[RawTVSeries]:
        """
        Fetch trending TV series for the current week (up to TMDB_MAX_PAGES pages).

        Returns:
            List of RawTVSeries objects. May be empty on failure.
        """
        series: List[RawTVSeries] = []
        total_pages = 1

        for page in range(1, TMDB_MAX_PAGES + 1):
            if page > total_pages:
                break

            data = self._get("/trending/tv/week", {"page": page})
            if data is None:
                logger.error("[TMDB] trending/tv/week page %d returned None.", page)
                break

            total_pages = min(data.get("total_pages", 1), TMDB_MAX_PAGES)
            results = data.get("results", [])

            for record in results:
                series_id = record.get("id")
                title = record.get("name") or record.get("original_name")
                if not series_id or not title:
                    logger.debug("Discarding TV record missing id or name: %s", record)
                    continue

                media_type = record.get("media_type", "tv")
                if media_type != "tv":
                    logger.debug("Discarding non-tv record (media_type=%s): %s", media_type, title)
                    continue

                series.append(RawTVSeries(
                    id=int(series_id),
                    title=str(title),
                    original_language=record.get("original_language", ""),
                    spoken_languages=self._extract_spoken_languages(record),
                    genre_ids=[int(g) for g in record.get("genre_ids", [])],
                    first_air_date=record.get("first_air_date", "") or "",
                    popularity=float(record.get("popularity", 0.0) or 0.0),
                    overview=record.get("overview", "") or "",
                    poster_path=record.get("poster_path"),
                ))

        logger.info("[TMDB] Fetched %d raw TV records (%d TMDB calls so far).", len(series), self._call_count)
        return series

    # ------------------------------------------------------------------
    # Discover endpoints (supplemental / fallback)
    # ------------------------------------------------------------------

    def discover_movies(self, genre_id: int, language: str) -> List[RawMovie]:
        """
        Discover movies by genre and language (up to TMDB_MAX_PAGES pages).

        Args:
            genre_id:  TMDB genre ID to filter by.
            language:  ISO 639-1 language code for original_language filter.

        Returns:
            List of RawMovie objects.
        """
        movies: List[RawMovie] = []
        total_pages = 1

        for page in range(1, TMDB_MAX_PAGES + 1):
            if page > total_pages:
                break

            data = self._get("/discover/movie", {
                "with_genres": genre_id,
                "with_original_language": language,
                "sort_by": "popularity.desc",
                "page": page,
            })
            if data is None:
                break

            total_pages = min(data.get("total_pages", 1), TMDB_MAX_PAGES)

            for record in data.get("results", []):
                movie_id = record.get("id")
                title = record.get("title") or record.get("original_title")
                if not movie_id or not title:
                    continue

                movies.append(RawMovie(
                    id=int(movie_id),
                    title=str(title),
                    original_language=record.get("original_language", ""),
                    spoken_languages=self._extract_spoken_languages(record),
                    genre_ids=[int(g) for g in record.get("genre_ids", [])],
                    release_date=record.get("release_date", "") or "",
                    popularity=float(record.get("popularity", 0.0) or 0.0),
                    overview=record.get("overview", "") or "",
                    poster_path=record.get("poster_path"),
                ))

        return movies

    def discover_tv(self, genre_id: int, language: str) -> List[RawTVSeries]:
        """
        Discover TV series by genre and language (up to TMDB_MAX_PAGES pages).

        Args:
            genre_id:  TMDB genre ID to filter by.
            language:  ISO 639-1 language code for original_language filter.

        Returns:
            List of RawTVSeries objects.
        """
        series: List[RawTVSeries] = []
        total_pages = 1

        for page in range(1, TMDB_MAX_PAGES + 1):
            if page > total_pages:
                break

            data = self._get("/discover/tv", {
                "with_genres": genre_id,
                "with_original_language": language,
                "sort_by": "popularity.desc",
                "page": page,
            })
            if data is None:
                break

            total_pages = min(data.get("total_pages", 1), TMDB_MAX_PAGES)

            for record in data.get("results", []):
                series_id = record.get("id")
                title = record.get("name") or record.get("original_name")
                if not series_id or not title:
                    continue

                series.append(RawTVSeries(
                    id=int(series_id),
                    title=str(title),
                    original_language=record.get("original_language", ""),
                    spoken_languages=self._extract_spoken_languages(record),
                    genre_ids=[int(g) for g in record.get("genre_ids", [])],
                    first_air_date=record.get("first_air_date", "") or "",
                    popularity=float(record.get("popularity", 0.0) or 0.0),
                    overview=record.get("overview", "") or "",
                    poster_path=record.get("poster_path"),
                ))

        return series

    # ------------------------------------------------------------------
    # External IDs (for retrieving IMDB ID)
    # ------------------------------------------------------------------

    def get_movie_external_ids(self, tmdb_id: int) -> Optional[str]:
        """
        Fetch the IMDB ID for a movie.

        Args:
            tmdb_id: The TMDB movie ID.

        Returns:
            The IMDB ID string (e.g. 'tt1234567'), or None if unavailable.
        """
        data = self._get(f"/movie/{tmdb_id}/external_ids")
        if data is None:
            logger.info("[TMDB] No external IDs for movie TMDB ID %d.", tmdb_id)
            return None
        imdb_id = data.get("imdb_id")
        if not imdb_id:
            logger.info("[TMDB] No IMDB ID for movie TMDB ID %d.", tmdb_id)
        return imdb_id or None

    def get_tv_external_ids(self, tmdb_id: int) -> Optional[str]:
        """
        Fetch the IMDB ID for a TV series.

        Args:
            tmdb_id: The TMDB TV series ID.

        Returns:
            The IMDB ID string (e.g. 'tt1234567'), or None if unavailable.
        """
        data = self._get(f"/tv/{tmdb_id}/external_ids")
        if data is None:
            logger.info("[TMDB] No external IDs for TV TMDB ID %d.", tmdb_id)
            return None
        imdb_id = data.get("imdb_id")
        if not imdb_id:
            logger.info("[TMDB] No IMDB ID for TV TMDB ID %d.", tmdb_id)
        return imdb_id or None

    # ------------------------------------------------------------------
    # Watch providers
    # ------------------------------------------------------------------

    def _resolve_ott_name(self, provider_name: str) -> Optional[str]:
        """
        Normalise a TMDB provider_name to a canonical OTT platform name.

        Uses exact alias lookup only (no substring matching) to avoid false
        positives such as matching "Sony" to "SonyLIV" or "Amazon" to
        "Amazon Prime Video".

        Args:
            provider_name: Raw provider name from TMDB response.

        Returns:
            Canonical name if it maps to a permitted platform, else None.
        """
        normalised = provider_name.strip().lower()
        # Exact alias lookup only — no substring fallback
        if normalised in OTT_NAME_ALIASES:
            return OTT_NAME_ALIASES[normalised]
        # Check if the normalised name exactly matches a canonical name
        for canonical in PERMITTED_OTT_NAMES:
            if normalised == canonical.lower():
                return canonical
        return None

    def get_movie_watch_providers(self, tmdb_id: int) -> List[str]:
        """
        Return Indian OTT platforms (flatrate/subscription) for a movie.

        Args:
            tmdb_id: TMDB movie ID.

        Returns:
            List of canonical OTT platform names available in India.
        """
        return self._get_watch_providers(f"/movie/{tmdb_id}/watch/providers", tmdb_id)

    def get_tv_watch_providers(self, tmdb_id: int) -> List[str]:
        """
        Return Indian OTT platforms (flatrate/subscription) for a TV series.

        Args:
            tmdb_id: TMDB TV series ID.

        Returns:
            List of canonical OTT platform names available in India.
        """
        return self._get_watch_providers(f"/tv/{tmdb_id}/watch/providers", tmdb_id)

    def _get_watch_providers(self, path: str, tmdb_id: int) -> List[str]:
        """
        Internal helper: extract IN flatrate providers from a watch/providers response.

        Args:
            path:     API path for the watch/providers endpoint.
            tmdb_id:  TMDB ID (used only for log messages).

        Returns:
            List of canonical OTT platform name strings.
        """
        data = self._get(path)
        if data is None:
            logger.info("[TMDB] Watch providers unavailable for TMDB ID %d.", tmdb_id)
            return []

        results = data.get("results", {})
        india_data = results.get("IN", {})
        if not india_data:
            logger.debug("[TMDB] No IN watch providers for TMDB ID %d.", tmdb_id)
            return []

        flatrate = india_data.get("flatrate", [])
        platforms: List[str] = []
        for entry in flatrate:
            raw_name = entry.get("provider_name", "")
            canonical = self._resolve_ott_name(raw_name)
            if canonical and canonical not in platforms:
                platforms.append(canonical)

        return platforms

    # ------------------------------------------------------------------
    # Poster image download
    # ------------------------------------------------------------------

    def download_poster(self, poster_path: str) -> Optional[bytes]:
        """
        Download a poster image from the TMDB CDN.

        Args:
            poster_path: The TMDB poster_path value (e.g. '/abcdef.jpg').

        Returns:
            Raw image bytes, or None if the download fails or the image is invalid.
        """
        url = f"{TMDB_IMAGE_BASE_URL}{poster_path}"
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = requests.get(url, timeout=20)
                if response.status_code == 200:
                    image_bytes = response.content
                    # Validate that Pillow can open it
                    Image.open(BytesIO(image_bytes)).verify()
                    return image_bytes
                if response.status_code == 404:
                    logger.warning("[TMDB] Poster 404 for path %s.", poster_path)
                    return None
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAYS[attempt - 1]
                    logger.warning(
                        "[TMDB] Poster download attempt %d failed (HTTP %d). Retrying in %ds.",
                        attempt, response.status_code, delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "[TMDB] Poster download failed after %d attempts for %s.",
                        MAX_RETRIES, poster_path,
                    )
                    return None
            except Exception as exc:
                if attempt < MAX_RETRIES:
                    delay = RETRY_DELAYS[attempt - 1]
                    logger.warning(
                        "[TMDB] Poster download attempt %d error (%s). Retrying in %ds.",
                        attempt, exc, delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "[TMDB] Poster download failed after %d attempts for %s: %s",
                        MAX_RETRIES, poster_path, exc,
                    )
                    return None
        return None

    @property
    def call_count(self) -> int:
        """Total number of TMDB API calls made by this client instance."""
        return self._call_count


# ---------------------------------------------------------------------------
# OMDb Client
# ---------------------------------------------------------------------------


class OMDbClient:
    """
    Client for the OMDb API.

    Retrieves IMDB rating and vote count for a given IMDB ID.
    Handles 'N/A' sentinel values and enforces the 500-call budget.
    """

    def __init__(self, api_key: str) -> None:
        """
        Initialise the client.

        Args:
            api_key: A valid OMDb API key.
        """
        self._api_key = api_key
        self._call_count: int = 0
        self._enriched_count: int = 0
        self._not_found_count: int = 0

    def fetch_ratings(self, imdb_id: str) -> tuple[Optional[float], int]:
        """
        Fetch IMDB rating and vote count for a title.

        Args:
            imdb_id: The IMDB title ID (e.g. 'tt1234567').

        Returns:
            A tuple of (imdb_rating, imdb_vote_count) where imdb_rating is a
            float between 1.0 and 10.0 or None, and imdb_vote_count is an int >= 0.

        Raises:
            FatalAPIError: On HTTP 401 (invalid OMDb API key).
        """
        if self._call_count >= OMDB_RATE_LIMIT_WARN:
            logger.warning(
                "[OMDB] Approaching rate limit: %d calls made. Skipping further OMDb enrichment.",
                self._call_count,
            )
            return None, 0

        self._call_count += 1

        data = _request_with_retry(
            OMDB_BASE_URL,
            {"i": imdb_id, "apikey": self._api_key},
            f"OMDb:{imdb_id}",
        )

        if data is None:
            logger.warning("[OMDB] No data returned for IMDB ID %s.", imdb_id)
            return None, 0

        if data.get("Response") == "False":
            logger.info("[OMDB] Not found for IMDB ID %s: %s", imdb_id, data.get("Error", ""))
            self._not_found_count += 1
            return None, 0

        # Parse rating
        raw_rating = data.get("imdbRating", "N/A")
        imdb_rating: Optional[float] = None
        if raw_rating and raw_rating != "N/A":
            try:
                imdb_rating = float(raw_rating)
            except ValueError:
                logger.warning("[OMDB] Could not parse imdbRating '%s' for %s.", raw_rating, imdb_id)

        # Parse vote count
        raw_votes = data.get("imdbVotes", "N/A")
        imdb_vote_count: int = 0
        if raw_votes and raw_votes != "N/A":
            try:
                # Remove commas: "1,234,567" -> 1234567
                imdb_vote_count = int(raw_votes.replace(",", ""))
            except ValueError:
                logger.warning("[OMDB] Could not parse imdbVotes '%s' for %s.", raw_votes, imdb_id)

        self._enriched_count += 1
        return imdb_rating, imdb_vote_count

    def log_summary(self) -> None:
        """Log a summary of OMDb call statistics."""
        logger.info(
            "[OMDB] Summary: %d calls, %d enriched, %d not found.",
            self._call_count, self._enriched_count, self._not_found_count,
        )

    @property
    def call_count(self) -> int:
        """Total number of OMDb API calls made by this client instance."""
        return self._call_count
