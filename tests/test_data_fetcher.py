"""
Tests for src/data_fetcher.py

Covers: UC-002, UC-003, UC-009, UC-010, UC-011, UC-015

All external HTTP calls are mocked — no real network requests are made.
"""

from io import BytesIO
from unittest.mock import MagicMock, patch, call

import pytest
from PIL import Image as PILImage

from src.data_fetcher import (
    FatalAPIError,
    OMDbClient,
    TMDBClient,
    _request_with_retry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status_code: int, json_data=None, content: bytes = b""):
    """Create a mock requests.Response object."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    if json_data is not None:
        mock_resp.json.return_value = json_data
    mock_resp.content = content
    mock_resp.text = str(json_data)[:500] if json_data else ""
    return mock_resp


def _make_valid_image_bytes() -> bytes:
    """Create minimal valid PNG image bytes for testing."""
    img = PILImage.new("RGB", (10, 10), color=(128, 128, 128))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# TMDBClient.fetch_trending_movies() — UC-002
# ---------------------------------------------------------------------------


class TestFetchTrendingMovies:
    """Happy path and error tests for fetch_trending_movies."""

    def test_fetch_trending_movies_returns_parsed_list(self, tmdb_trending_movies_response):
        """Happy path: correctly parses and returns a list of RawMovie objects (UC-002)."""
        client = TMDBClient(api_key="fake_key")
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, tmdb_trending_movies_response)
            movies = client.fetch_trending_movies()

        assert len(movies) == 3
        movie = movies[0]
        assert movie.id == 101
        assert movie.title == "Action Hero"
        assert movie.original_language == "hi"
        assert movie.genre_ids == [28, 18]
        assert movie.popularity == 200.5
        assert movie.poster_path == "/action_hero.jpg"

    def test_fetch_trending_movies_empty_results(self):
        """Returns empty list when API response has no results."""
        client = TMDBClient(api_key="fake_key")
        empty_response = {"page": 1, "total_pages": 1, "total_results": 0, "results": []}
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, empty_response)
            movies = client.fetch_trending_movies()

        assert movies == []

    def test_fetch_trending_movies_discards_records_missing_id(self):
        """Records missing 'id' are discarded (UC-002 AC-2)."""
        client = TMDBClient(api_key="fake_key")
        response = {
            "page": 1,
            "total_pages": 1,
            "total_results": 2,
            "results": [
                {
                    "id": None,  # missing id
                    "title": "No ID Movie",
                    "original_language": "en",
                    "spoken_languages": [],
                    "genre_ids": [28],
                    "release_date": "2025-01-01",
                    "popularity": 50.0,
                    "overview": "A movie without an ID.",
                    "poster_path": None,
                },
                {
                    "id": 999,
                    "title": "Valid Movie",
                    "original_language": "en",
                    "spoken_languages": [],
                    "genre_ids": [28],
                    "release_date": "2025-01-01",
                    "popularity": 50.0,
                    "overview": "A valid movie.",
                    "poster_path": None,
                },
            ],
        }
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, response)
            movies = client.fetch_trending_movies()

        assert len(movies) == 1
        assert movies[0].id == 999

    def test_fetch_trending_movies_discards_records_missing_title(self):
        """Records missing both 'title' and 'original_title' are discarded (UC-002 AC-2)."""
        client = TMDBClient(api_key="fake_key")
        response = {
            "page": 1,
            "total_pages": 1,
            "total_results": 1,
            "results": [
                {
                    "id": 888,
                    "title": None,
                    "original_title": None,
                    "original_language": "en",
                    "spoken_languages": [],
                    "genre_ids": [28],
                    "release_date": "2025-01-01",
                    "popularity": 50.0,
                    "overview": "A movie without a title.",
                    "poster_path": None,
                },
            ],
        }
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, response)
            movies = client.fetch_trending_movies()

        assert len(movies) == 0


# ---------------------------------------------------------------------------
# TMDBClient.fetch_trending_tv() — UC-003
# ---------------------------------------------------------------------------


class TestFetchTrendingTV:
    """Happy path and error tests for fetch_trending_tv."""

    def test_fetch_trending_tv_returns_parsed_list(self, tmdb_trending_tv_response):
        """Happy path: correctly parses and returns a list of RawTVSeries objects (UC-003)."""
        client = TMDBClient(api_key="fake_key")
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, tmdb_trending_tv_response)
            series = client.fetch_trending_tv()

        # Only 2 of 3 records have media_type="tv" or no media_type; the Tamil one
        # has media_type="tv" too but let's check all are included
        assert len(series) >= 2
        first = series[0]
        assert first.id == 201
        assert first.title == "Hindi Comedy Series"
        assert first.original_language == "hi"

    def test_fetch_trending_tv_uses_name_field_not_title(self, tmdb_trending_tv_response):
        """TV series uses 'name' field for title, not 'title' (UC-003 AC-4)."""
        client = TMDBClient(api_key="fake_key")
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, tmdb_trending_tv_response)
            series = client.fetch_trending_tv()

        titles = [s.title for s in series]
        assert "Hindi Comedy Series" in titles
        assert "English Drama Series" in titles

    def test_fetch_trending_tv_discards_non_tv_media_type(self):
        """Records with media_type != 'tv' are discarded (UC-003 AF-6)."""
        client = TMDBClient(api_key="fake_key")
        response = {
            "page": 1,
            "total_pages": 1,
            "total_results": 2,
            "results": [
                {
                    "id": 301,
                    "name": "A Movie in TV Endpoint",
                    "original_name": "A Movie in TV Endpoint",
                    "original_language": "en",
                    "spoken_languages": [],
                    "genre_ids": [18],
                    "first_air_date": "2025-01-01",
                    "popularity": 50.0,
                    "overview": "Not a TV series.",
                    "poster_path": None,
                    "media_type": "movie",  # Wrong media_type — should be discarded
                },
                {
                    "id": 302,
                    "name": "Valid TV Series",
                    "original_name": "Valid TV Series",
                    "original_language": "en",
                    "spoken_languages": [],
                    "genre_ids": [18],
                    "first_air_date": "2025-01-01",
                    "popularity": 50.0,
                    "overview": "A real TV series.",
                    "poster_path": None,
                    "media_type": "tv",
                },
            ],
        }
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, response)
            series = client.fetch_trending_tv()

        assert len(series) == 1
        assert series[0].id == 302


# ---------------------------------------------------------------------------
# OMDbClient.fetch_ratings() — UC-009
# ---------------------------------------------------------------------------


class TestOMDbFetchRatings:
    """Tests for OMDb rating fetching and parsing."""

    def test_fetch_ratings_parses_valid_response(self, omdb_success_response):
        """Happy path: correctly parses imdbRating as float and imdbVotes as int (UC-009 AC-1)."""
        client = OMDbClient(api_key="fake_omdb_key")
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, omdb_success_response)
            rating, votes = client.fetch_ratings("tt1234567")

        assert rating == 7.5
        assert isinstance(rating, float)
        assert votes == 1234567
        assert isinstance(votes, int)

    def test_fetch_ratings_na_returns_none_not_raises(self, omdb_na_response):
        """OMDb 'N/A' for imdbRating returns None without raising (UC-009 AF-3, AC-2)."""
        client = OMDbClient(api_key="fake_omdb_key")
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, omdb_na_response)
            rating, votes = client.fetch_ratings("tt9999999")

        assert rating is None
        assert votes == 0

    def test_fetch_ratings_na_votes_returns_zero(self, omdb_na_response):
        """OMDb 'N/A' for imdbVotes returns 0 without raising (UC-009 AF-4)."""
        client = OMDbClient(api_key="fake_omdb_key")
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, omdb_na_response)
            _, votes = client.fetch_ratings("tt9999999")

        assert votes == 0

    def test_fetch_ratings_comma_votes_parsed_correctly(self):
        """imdbVotes '1,234,567' is parsed to integer 1234567 (UC-009 AC-4)."""
        client = OMDbClient(api_key="fake_omdb_key")
        response = {
            "Title": "Test Movie",
            "imdbRating": "7.5",
            "imdbVotes": "1,234,567",
            "Response": "True",
        }
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, response)
            rating, votes = client.fetch_ratings("tt1234567")

        assert votes == 1234567

    def test_fetch_ratings_not_found_returns_none(self, omdb_not_found_response):
        """OMDb 'Movie not found' returns (None, 0) without raising (UC-009 AF-2)."""
        client = OMDbClient(api_key="fake_omdb_key")
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, omdb_not_found_response)
            rating, votes = client.fetch_ratings("tt0000000")

        assert rating is None
        assert votes == 0


# ---------------------------------------------------------------------------
# Retry logic — UC-015
# ---------------------------------------------------------------------------


class TestRetryLogic:
    """Tests for exponential backoff retry behavior."""

    def test_retry_on_429_makes_multiple_calls(self):
        """On HTTP 429, the client retries — verify multiple calls are made (UC-015 AF-2)."""
        client = TMDBClient(api_key="fake_key")
        resp_429 = _make_response(429)
        resp_200 = _make_response(200, {"page": 1, "total_pages": 1, "total_results": 0, "results": []})

        with patch("src.data_fetcher.requests.get") as mock_get, \
             patch("src.data_fetcher.time.sleep"):
            mock_get.side_effect = [resp_429, resp_200]
            movies = client.fetch_trending_movies()

        assert mock_get.call_count == 2

    def test_retry_on_503_makes_multiple_calls(self):
        """On HTTP 503, the client retries — verify multiple calls are made (UC-015 AF-2)."""
        client = TMDBClient(api_key="fake_key")
        resp_503 = _make_response(503)
        resp_200 = _make_response(200, {"page": 1, "total_pages": 1, "total_results": 0, "results": []})

        with patch("src.data_fetcher.requests.get") as mock_get, \
             patch("src.data_fetcher.time.sleep"):
            mock_get.side_effect = [resp_503, resp_200]
            movies = client.fetch_trending_movies()

        assert mock_get.call_count == 2

    def test_fatal_on_401_raises_immediately_no_retries(self):
        """HTTP 401 raises FatalAPIError immediately without retrying (UC-015 AF-1, AC-3)."""
        client = TMDBClient(api_key="bad_key")
        resp_401 = _make_response(401)

        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = resp_401
            with pytest.raises(FatalAPIError):
                client.fetch_trending_movies()

        # Only 1 call made — no retry
        assert mock_get.call_count == 1

    def test_fatal_api_error_is_raised_not_swallowed(self):
        """FatalAPIError propagates through fetch_trending_movies (UC-015 AC-3)."""
        client = TMDBClient(api_key="bad_key")
        resp_401 = _make_response(401)

        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = resp_401
            with pytest.raises(FatalAPIError) as exc_info:
                client.fetch_trending_movies()

        assert "401" in str(exc_info.value)

    def test_all_retries_exhausted_returns_empty(self):
        """When all 3 retries fail with 500, returns empty list (UC-015 step 8)."""
        client = TMDBClient(api_key="fake_key")
        resp_500 = _make_response(500)

        with patch("src.data_fetcher.requests.get") as mock_get, \
             patch("src.data_fetcher.time.sleep"):
            mock_get.return_value = resp_500
            movies = client.fetch_trending_movies()

        # 3 attempts for MAX_RETRIES=3
        assert mock_get.call_count == 3
        assert movies == []


# ---------------------------------------------------------------------------
# Watch providers — UC-010
# ---------------------------------------------------------------------------


class TestWatchProviders:
    """Tests for India OTT watch provider fetching."""

    def test_get_movie_watch_providers_returns_india_flatrate_names(
        self, tmdb_watch_providers_india_response
    ):
        """Returns correct OTT names for India flatrate providers (UC-010 AC-1)."""
        client = TMDBClient(api_key="fake_key")
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, tmdb_watch_providers_india_response)
            platforms = client.get_movie_watch_providers(101)

        assert "Netflix" in platforms
        assert "Amazon Prime Video" in platforms

    def test_get_movie_watch_providers_empty_when_no_india(
        self, tmdb_watch_providers_no_india_response
    ):
        """Returns empty list when no India ('IN') providers exist (UC-010 AC-2)."""
        client = TMDBClient(api_key="fake_key")
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, tmdb_watch_providers_no_india_response)
            platforms = client.get_movie_watch_providers(102)

        assert platforms == []

    def test_get_tv_watch_providers_returns_india_flatrate_names(
        self, tmdb_watch_providers_india_response
    ):
        """Returns correct OTT names for TV series India flatrate providers (UC-010)."""
        client = TMDBClient(api_key="fake_key")
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, tmdb_watch_providers_india_response)
            platforms = client.get_tv_watch_providers(201)

        assert len(platforms) >= 1
        assert "Netflix" in platforms

    def test_watch_providers_empty_when_api_fails(self):
        """Returns empty list when API returns None/error (UC-015 fallback)."""
        client = TMDBClient(api_key="fake_key")
        with patch("src.data_fetcher.requests.get") as mock_get, \
             patch("src.data_fetcher.time.sleep"):
            mock_get.return_value = _make_response(500)
            platforms = client.get_movie_watch_providers(999)

        assert platforms == []

    def test_watch_providers_normalizes_prime_video_alias(self):
        """'Prime Video' alias is normalized to 'Amazon Prime Video' (UC-010 AC-3)."""
        client = TMDBClient(api_key="fake_key")
        response = {
            "id": 200,
            "results": {
                "IN": {
                    "flatrate": [
                        {"provider_id": 119, "provider_name": "Prime Video", "display_priority": 1},
                    ],
                },
            },
        }
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, response)
            platforms = client.get_movie_watch_providers(200)

        assert "Amazon Prime Video" in platforms

    def test_watch_providers_excludes_non_permitted_platforms(self):
        """Non-permitted platforms like 'Mubi' produce empty OTT list (UC-010 AC-4)."""
        client = TMDBClient(api_key="fake_key")
        response = {
            "id": 300,
            "results": {
                "IN": {
                    "flatrate": [
                        {"provider_id": 999, "provider_name": "Mubi", "display_priority": 1},
                    ],
                },
            },
        }
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, response)
            platforms = client.get_movie_watch_providers(300)

        assert platforms == []


# ---------------------------------------------------------------------------
# Poster download — UC-011
# ---------------------------------------------------------------------------


class TestPosterDownload:
    """Tests for poster image download with retry and fallback."""

    def test_download_poster_returns_bytes_on_success(self):
        """Returns raw image bytes when download succeeds (UC-011 AC-1)."""
        client = TMDBClient(api_key="fake_key")
        valid_image_bytes = _make_valid_image_bytes()

        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, content=valid_image_bytes)
            result = client.download_poster("/valid_poster.jpg")

        assert result is not None
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_download_poster_returns_none_on_404(self):
        """Returns None (no raise) when poster not found (HTTP 404) (UC-011 AC-3, UC-015 AF-3)."""
        client = TMDBClient(api_key="fake_key")

        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(404)
            result = client.download_poster("/missing_poster.jpg")

        assert result is None

    def test_download_poster_returns_none_on_http_error(self):
        """Returns None (no raise) when HTTP error occurs after retries (UC-011 AF-2)."""
        client = TMDBClient(api_key="fake_key")

        with patch("src.data_fetcher.requests.get") as mock_get, \
             patch("src.data_fetcher.time.sleep"):
            mock_get.return_value = _make_response(500)
            result = client.download_poster("/broken_poster.jpg")

        assert result is None

    def test_download_poster_returns_none_on_exception(self):
        """Returns None (no raise) when a network exception occurs."""
        client = TMDBClient(api_key="fake_key")

        with patch("src.data_fetcher.requests.get") as mock_get, \
             patch("src.data_fetcher.time.sleep"):
            mock_get.side_effect = Exception("Connection timeout")
            result = client.download_poster("/timeout_poster.jpg")

        assert result is None


# ---------------------------------------------------------------------------
# _request_with_retry — low-level retry function
# ---------------------------------------------------------------------------


class TestRequestWithRetry:
    """Tests for the private _request_with_retry helper."""

    def test_returns_json_on_200(self):
        """Returns parsed JSON dict on HTTP 200 success."""
        expected = {"key": "value"}
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(200, expected)
            result = _request_with_retry("https://example.com/api", {}, "test")

        assert result == expected

    def test_raises_fatal_on_401(self):
        """Raises FatalAPIError immediately on HTTP 401 (UC-015 AF-1, AC-3)."""
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(401)
            with pytest.raises(FatalAPIError):
                _request_with_retry("https://example.com/api", {}, "test")

        # Verify no retry — only 1 call
        assert mock_get.call_count == 1

    def test_returns_none_on_404(self):
        """Returns None immediately on HTTP 404 (non-retriable)."""
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(404)
            result = _request_with_retry("https://example.com/api", {}, "test")

        assert result is None
        assert mock_get.call_count == 1

    def test_returns_none_on_400(self):
        """Returns None immediately on HTTP 400 (non-retriable)."""
        with patch("src.data_fetcher.requests.get") as mock_get:
            mock_get.return_value = _make_response(400)
            result = _request_with_retry("https://example.com/api", {}, "test")

        assert result is None
        assert mock_get.call_count == 1

    def test_retries_on_429_succeeds_on_second_attempt(self):
        """Retries on 429 and succeeds on second attempt (UC-015 AC-1)."""
        expected = {"success": True}
        with patch("src.data_fetcher.requests.get") as mock_get, \
             patch("src.data_fetcher.time.sleep"):
            mock_get.side_effect = [_make_response(429), _make_response(200, expected)]
            result = _request_with_retry("https://example.com/api", {}, "test")

        assert result == expected
        assert mock_get.call_count == 2
