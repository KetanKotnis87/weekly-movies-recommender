"""
Shared pytest fixtures for the Weekly Movie Recommender test suite.

Provides:
- Mock TMDB API responses for movies and TV series
- Mock OMDb API responses
- Sample ContentItem fixtures for all 4 genres and 3 languages
- Config fixture with test environment variables
- Temp output directory fixture
"""

import os
import tempfile
from datetime import date, timedelta

import pytest

from src.scorer import ContentItem


# ---------------------------------------------------------------------------
# Config / env var fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_env_vars(monkeypatch):
    """Set all required environment variables for testing."""
    monkeypatch.setenv("TMDB_API_KEY", "test_tmdb_key_12345")
    monkeypatch.setenv("OMDB_API_KEY", "test_omdb_key_12345")
    monkeypatch.setenv("GMAIL_ADDRESS", "test@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "testapppassword1")
    monkeypatch.setenv("RECIPIENT_EMAIL", "recipient@example.com")
    return {
        "TMDB_API_KEY": "test_tmdb_key_12345",
        "OMDB_API_KEY": "test_omdb_key_12345",
        "GMAIL_ADDRESS": "test@gmail.com",
        "GMAIL_APP_PASSWORD": "testapppassword1",
        "RECIPIENT_EMAIL": "recipient@example.com",
    }


@pytest.fixture
def test_config(test_env_vars):
    """Return a validated Config object using test environment variables."""
    from src.config import Config
    return Config()


# ---------------------------------------------------------------------------
# Temp output directory
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_output_dir(tmp_path):
    """Provide a temporary directory for PDF and sentinel file output."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def today():
    return date.today()


@pytest.fixture
def recent_date():
    """A date 100 days ago (well within 365-day recency window)."""
    return (date.today() - timedelta(days=100)).strftime("%Y-%m-%d")


@pytest.fixture
def boundary_date():
    """A date exactly 365 days ago (should pass recency filter)."""
    return (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")


@pytest.fixture
def old_date():
    """A date 366 days ago (should fail recency filter)."""
    return (date.today() - timedelta(days=366)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# TMDB API response mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def tmdb_trending_movies_response():
    """Realistic TMDB /trending/movie/week response (single page)."""
    return {
        "page": 1,
        "total_pages": 1,
        "total_results": 3,
        "results": [
            {
                "id": 101,
                "title": "Action Hero",
                "original_title": "Action Hero",
                "original_language": "hi",
                "spoken_languages": [{"iso_639_1": "hi", "name": "Hindi"}],
                "genre_ids": [28, 18],
                "release_date": (date.today() - timedelta(days=100)).strftime("%Y-%m-%d"),
                "popularity": 200.5,
                "overview": "A Hindi action drama about a hero fighting crime in Mumbai.",
                "poster_path": "/action_hero.jpg",
                "media_type": "movie",
            },
            {
                "id": 102,
                "title": "English Thriller",
                "original_title": "English Thriller",
                "original_language": "en",
                "spoken_languages": [{"iso_639_1": "en", "name": "English"}],
                "genre_ids": [53],
                "release_date": (date.today() - timedelta(days=50)).strftime("%Y-%m-%d"),
                "popularity": 150.3,
                "overview": "A gripping English thriller about corporate espionage.",
                "poster_path": "/english_thriller.jpg",
                "media_type": "movie",
            },
            {
                "id": 103,
                "title": "Kannada Drama",
                "original_title": "Kannada Drama",
                "original_language": "kn",
                "spoken_languages": [{"iso_639_1": "kn", "name": "Kannada"}],
                "genre_ids": [18],
                "release_date": (date.today() - timedelta(days=200)).strftime("%Y-%m-%d"),
                "popularity": 75.8,
                "overview": "A moving Kannada drama about family values.",
                "poster_path": "/kannada_drama.jpg",
                "media_type": "movie",
            },
        ],
    }


@pytest.fixture
def tmdb_trending_tv_response():
    """Realistic TMDB /trending/tv/week response (single page)."""
    return {
        "page": 1,
        "total_pages": 1,
        "total_results": 3,
        "results": [
            {
                "id": 201,
                "name": "Hindi Comedy Series",
                "original_name": "Hindi Comedy Series",
                "original_language": "hi",
                "spoken_languages": [{"iso_639_1": "hi", "name": "Hindi"}],
                "genre_ids": [35],
                "first_air_date": (date.today() - timedelta(days=80)).strftime("%Y-%m-%d"),
                "popularity": 180.0,
                "overview": "A hilarious Hindi comedy series set in Delhi.",
                "poster_path": "/hindi_comedy.jpg",
                "media_type": "tv",
            },
            {
                "id": 202,
                "name": "English Drama Series",
                "original_name": "English Drama Series",
                "original_language": "en",
                "spoken_languages": [{"iso_639_1": "en", "name": "English"}],
                "genre_ids": [18, 10759],
                "first_air_date": (date.today() - timedelta(days=30)).strftime("%Y-%m-%d"),
                "popularity": 220.0,
                "overview": "An English drama series about political intrigue.",
                "poster_path": "/english_drama.jpg",
                "media_type": "tv",
            },
            {
                "id": 203,
                "name": "Tamil Series (should be filtered)",
                "original_name": "Tamil Series",
                "original_language": "ta",
                "spoken_languages": [{"iso_639_1": "ta", "name": "Tamil"}],
                "genre_ids": [18],
                "first_air_date": (date.today() - timedelta(days=60)).strftime("%Y-%m-%d"),
                "popularity": 90.0,
                "overview": "A Tamil drama series.",
                "poster_path": "/tamil_drama.jpg",
                "media_type": "tv",
            },
        ],
    }


@pytest.fixture
def tmdb_watch_providers_india_response():
    """TMDB watch/providers response with India flatrate providers."""
    return {
        "id": 101,
        "results": {
            "IN": {
                "link": "https://www.themoviedb.org/movie/101/watch?locale=IN",
                "flatrate": [
                    {"provider_id": 8, "provider_name": "Netflix", "display_priority": 1},
                    {"provider_id": 119, "provider_name": "Amazon Prime Video", "display_priority": 2},
                ],
                "rent": [],
                "buy": [],
            },
            "US": {
                "flatrate": [
                    {"provider_id": 8, "provider_name": "Netflix", "display_priority": 1},
                ],
            },
        },
    }


@pytest.fixture
def tmdb_watch_providers_no_india_response():
    """TMDB watch/providers response with NO India providers."""
    return {
        "id": 102,
        "results": {
            "US": {
                "flatrate": [
                    {"provider_id": 8, "provider_name": "Netflix", "display_priority": 1},
                ],
            },
        },
    }


@pytest.fixture
def tmdb_external_ids_response():
    """TMDB external_ids response with a valid IMDB ID."""
    return {
        "id": 101,
        "imdb_id": "tt1234567",
        "wikidata_id": "Q12345",
    }


# ---------------------------------------------------------------------------
# OMDb API response mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def omdb_success_response():
    """Successful OMDb response with valid rating and votes."""
    return {
        "Title": "Action Hero",
        "Year": "2024",
        "imdbID": "tt1234567",
        "imdbRating": "7.5",
        "imdbVotes": "1,234,567",
        "Response": "True",
    }


@pytest.fixture
def omdb_na_response():
    """OMDb response with N/A for rating and votes."""
    return {
        "Title": "Unknown Movie",
        "Year": "2024",
        "imdbID": "tt9999999",
        "imdbRating": "N/A",
        "imdbVotes": "N/A",
        "Response": "True",
    }


@pytest.fixture
def omdb_not_found_response():
    """OMDb not found response."""
    return {
        "Response": "False",
        "Error": "Movie not found!",
    }


# ---------------------------------------------------------------------------
# ContentItem fixtures
# ---------------------------------------------------------------------------


def _make_item(
    tmdb_id: int,
    title: str,
    media_type: str,
    genres: list,
    language: str,
    release_date: str,
    popularity: float = 100.0,
    imdb_rating: float = 7.0,
    vote_count: int = 1000,
    ott_platforms: list = None,
    overview: str = "A great film about something interesting.",
    poster_image: bytes = None,
):
    """Helper to create a ContentItem for testing."""
    from src.scorer import score_item
    item = ContentItem(
        id=tmdb_id,
        title=title,
        media_type=media_type,
        genres=genres,
        language=language,
        release_date=release_date,
        tmdb_popularity=popularity,
        imdb_rating=imdb_rating,
        vote_count=vote_count,
        overview=overview,
        poster_path=f"/{title.lower().replace(' ', '_')}.jpg",
        ott_platforms=ott_platforms if ott_platforms is not None else ["Netflix"],
        poster_image=poster_image,
    )
    item.score = score_item(item)
    return item


@pytest.fixture
def recent_date_str():
    return (date.today() - timedelta(days=100)).strftime("%Y-%m-%d")


@pytest.fixture
def hindi_action_movie(recent_date_str):
    return _make_item(
        tmdb_id=1001,
        title="Hindi Action Movie",
        media_type="movie",
        genres=["Action"],
        language="hi",
        release_date=recent_date_str,
        popularity=120.0,
        imdb_rating=7.2,
        vote_count=5000,
        ott_platforms=["Netflix"],
    )


@pytest.fixture
def english_thriller_movie(recent_date_str):
    return _make_item(
        tmdb_id=1002,
        title="English Thriller Movie",
        media_type="movie",
        genres=["Thriller"],
        language="en",
        release_date=recent_date_str,
        popularity=90.0,
        imdb_rating=7.8,
        vote_count=8000,
        ott_platforms=["Amazon Prime Video"],
    )


@pytest.fixture
def kannada_drama_movie(recent_date_str):
    return _make_item(
        tmdb_id=1003,
        title="Kannada Drama Movie",
        media_type="movie",
        genres=["Drama"],
        language="kn",
        release_date=recent_date_str,
        popularity=60.0,
        imdb_rating=7.5,
        vote_count=2000,
        ott_platforms=["Disney+ Hotstar"],
    )


@pytest.fixture
def hindi_comedy_series(recent_date_str):
    return _make_item(
        tmdb_id=2001,
        title="Hindi Comedy Series",
        media_type="tv",
        genres=["Comedy"],
        language="hi",
        release_date=recent_date_str,
        popularity=85.0,
        imdb_rating=7.0,
        vote_count=3000,
        ott_platforms=["JioCinema"],
    )


@pytest.fixture
def multi_genre_item(recent_date_str):
    """A ContentItem that qualifies for both Action and Drama genres."""
    return _make_item(
        tmdb_id=3001,
        title="Action Drama Film",
        media_type="movie",
        genres=["Action", "Drama"],
        language="en",
        release_date=recent_date_str,
        popularity=150.0,
        imdb_rating=8.0,
        vote_count=10000,
        ott_platforms=["Netflix", "Amazon Prime Video"],
    )


@pytest.fixture
def sample_recommendations(
    hindi_action_movie,
    english_thriller_movie,
    kannada_drama_movie,
    hindi_comedy_series,
    recent_date_str,
):
    """Full recommendations dict with all 4 genres populated."""
    # Create more items for all genres
    action_items = [
        hindi_action_movie,
        _make_item(1011, "Action Film 2", "movie", ["Action"], "en", recent_date_str, 110.0, 7.5, 4000, ["Netflix"]),
        _make_item(1012, "Action Film 3", "movie", ["Action"], "kn", recent_date_str, 80.0, 6.8, 1500, ["SonyLIV"]),
    ]
    thriller_items = [
        english_thriller_movie,
        _make_item(1021, "Thriller 2", "movie", ["Thriller"], "hi", recent_date_str, 95.0, 7.6, 7000, ["Amazon Prime Video"]),
        _make_item(1022, "Thriller 3", "movie", ["Thriller"], "en", recent_date_str, 70.0, 7.2, 3500, ["Netflix"]),
    ]
    drama_items = [
        kannada_drama_movie,
        _make_item(1031, "Drama 2", "movie", ["Drama"], "hi", recent_date_str, 65.0, 7.4, 2500, ["Disney+ Hotstar"]),
        _make_item(1032, "Drama 3", "movie", ["Drama"], "en", recent_date_str, 55.0, 7.1, 1800, ["Netflix"]),
    ]
    comedy_items = [
        _make_item(1041, "Comedy 1", "movie", ["Comedy"], "hi", recent_date_str, 75.0, 6.9, 2200, ["JioCinema"]),
        _make_item(1042, "Comedy 2", "movie", ["Comedy"], "en", recent_date_str, 65.0, 7.3, 3000, ["Netflix"]),
        _make_item(1043, "Comedy 3", "movie", ["Comedy"], "kn", recent_date_str, 50.0, 6.7, 1200, ["Zee5"]),
    ]
    series_action = [
        _make_item(2011, "Action Series 1", "tv", ["Action"], "en", recent_date_str, 130.0, 7.8, 9000, ["Netflix"]),
        _make_item(2012, "Action Series 2", "tv", ["Action"], "hi", recent_date_str, 100.0, 7.2, 4500, ["Amazon Prime Video"]),
        _make_item(2013, "Action Series 3", "tv", ["Action"], "kn", recent_date_str, 70.0, 7.0, 2000, ["SonyLIV"]),
    ]
    series_comedy = [
        hindi_comedy_series,
        _make_item(2021, "Comedy Series 2", "tv", ["Comedy"], "en", recent_date_str, 90.0, 7.5, 6000, ["Netflix"]),
        _make_item(2022, "Comedy Series 3", "tv", ["Comedy"], "kn", recent_date_str, 60.0, 6.8, 1800, ["Zee5"]),
    ]

    return {
        "movies": {
            "Action": action_items,
            "Thriller": thriller_items,
            "Drama": drama_items,
            "Comedy": comedy_items,
        },
        "series": {
            "Action": series_action,
            "Comedy": series_comedy,
        },
    }
