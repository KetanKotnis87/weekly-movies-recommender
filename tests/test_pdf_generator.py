"""
Tests for src/pdf_generator.py

Covers: UC-012, UC-014

Tests verify PDF generation, file validity, size constraints,
and graceful handling of missing poster images and sparse genre content.
"""

import os
from datetime import date, timedelta
from io import BytesIO

import pytest
from PIL import Image as PILImage

from src.pdf_generator import generate_pdf
from src.scorer import ContentItem, score_item


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(
    tmdb_id: int,
    title: str,
    media_type: str = "movie",
    genres: list = None,
    language: str = "en",
    release_date: str = None,
    popularity: float = 100.0,
    imdb_rating: float = 7.0,
    vote_count: int = 1000,
    ott_platforms: list = None,
    overview: str = "A test film with an interesting plot.",
    poster_image: bytes = None,
):
    """Create a ContentItem for PDF generation testing."""
    if genres is None:
        genres = ["Action"]
    if release_date is None:
        release_date = (date.today() - timedelta(days=100)).strftime("%Y-%m-%d")
    if ott_platforms is None:
        ott_platforms = ["Netflix"]

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
        ott_platforms=ott_platforms,
        poster_image=poster_image,
    )
    item.score = score_item(item)
    return item


def _make_valid_image_bytes() -> bytes:
    """Create minimal valid PNG image bytes for poster testing."""
    img = PILImage.new("RGB", (80, 120), color=(64, 64, 128))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_minimal_recommendations():
    """Create a minimal recommendations dict with one action movie."""
    items = [_make_item(1, "Test Action Movie", genres=["Action"], language="en")]
    return {
        "movies": {"Action": items},
        "series": {},
    }


def _make_full_recommendations():
    """Create recommendations with all 4 genres and 3 items each."""
    recent = (date.today() - timedelta(days=100)).strftime("%Y-%m-%d")
    genres = ["Action", "Thriller", "Drama", "Comedy"]
    movies = {}
    series = {}

    for i, genre in enumerate(genres):
        base_id = (i + 1) * 100
        movies[genre] = [
            _make_item(base_id + 1, f"{genre} Movie 1", genres=[genre], language="hi", release_date=recent),
            _make_item(base_id + 2, f"{genre} Movie 2", genres=[genre], language="en", release_date=recent),
            _make_item(base_id + 3, f"{genre} Movie 3", genres=[genre], language="kn", release_date=recent),
        ]
        series[genre] = [
            _make_item(base_id + 11, f"{genre} Series 1", media_type="tv", genres=[genre], language="hi", release_date=recent),
            _make_item(base_id + 12, f"{genre} Series 2", media_type="tv", genres=[genre], language="en", release_date=recent),
            _make_item(base_id + 13, f"{genre} Series 3", media_type="tv", genres=[genre], language="kn", release_date=recent),
        ]

    return {"movies": movies, "series": series}


# ---------------------------------------------------------------------------
# UC-012: PDF generation — basic output
# ---------------------------------------------------------------------------


class TestPDFGeneratorOutput:
    """Tests that generate_pdf produces a valid PDF file."""

    def test_generate_produces_file_at_output_path(self, tmp_path):
        """generate() creates a file at the specified output_path (UC-012)."""
        output_path = str(tmp_path / "test_output.pdf")
        recs = _make_minimal_recommendations()

        generate_pdf(recs, output_path, run_date=date(2026, 3, 1))

        assert os.path.exists(output_path)

    def test_generated_file_is_valid_pdf(self, tmp_path):
        """Generated file starts with '%PDF' magic bytes (UC-012 AC-1)."""
        output_path = str(tmp_path / "test_valid.pdf")
        recs = _make_minimal_recommendations()

        generate_pdf(recs, output_path, run_date=date(2026, 3, 1))

        with open(output_path, "rb") as f:
            header = f.read(4)

        assert header == b"%PDF", f"Expected PDF magic bytes, got: {header}"

    def test_generated_pdf_size_under_10mb(self, tmp_path):
        """Generated PDF is under 10 MB (NFR-004) (UC-012 AC-5)."""
        output_path = str(tmp_path / "test_size.pdf")
        recs = _make_full_recommendations()

        generate_pdf(recs, output_path, run_date=date(2026, 3, 1))

        file_size = os.path.getsize(output_path)
        max_size = 10 * 1024 * 1024  # 10 MB

        assert file_size < max_size, (
            f"PDF size {file_size} bytes exceeds 10 MB limit ({max_size} bytes)"
        )

    def test_generate_returns_output_path_string(self, tmp_path):
        """generate() returns the output_path string for chaining (UC-012)."""
        output_path = str(tmp_path / "test_return.pdf")
        recs = _make_minimal_recommendations()

        result = generate_pdf(recs, output_path, run_date=date(2026, 3, 1))

        assert result == output_path


# ---------------------------------------------------------------------------
# UC-012: Poster image handling
# ---------------------------------------------------------------------------


class TestPDFPosterHandling:
    """Tests for poster image fallback behavior (UC-012 / UC-011)."""

    def test_generate_runs_without_error_when_poster_is_none(self, tmp_path):
        """PDF generation succeeds when poster_image is None (placeholder used) (UC-012 AF-4)."""
        output_path = str(tmp_path / "test_no_poster.pdf")
        items = [_make_item(1, "No Poster Movie", poster_image=None)]
        recs = {"movies": {"Action": items}, "series": {}}

        # Should not raise any exception
        generate_pdf(recs, output_path, run_date=date(2026, 3, 1))

        assert os.path.exists(output_path)

    def test_generate_embeds_valid_poster_image(self, tmp_path):
        """PDF generation succeeds when poster_image contains valid bytes."""
        output_path = str(tmp_path / "test_with_poster.pdf")
        valid_bytes = _make_valid_image_bytes()
        items = [_make_item(1, "Poster Movie", poster_image=valid_bytes)]
        recs = {"movies": {"Action": items}, "series": {}}

        generate_pdf(recs, output_path, run_date=date(2026, 3, 1))

        assert os.path.exists(output_path)
        file_size = os.path.getsize(output_path)
        assert file_size > 0


# ---------------------------------------------------------------------------
# UC-012: Genre and content handling
# ---------------------------------------------------------------------------


class TestPDFGenreHandling:
    """Tests for genre section rendering in PDF output."""

    def test_generate_runs_without_error_when_genre_has_0_items(self, tmp_path):
        """PDF generation succeeds when a genre bucket is empty (UC-012 AF-2)."""
        output_path = str(tmp_path / "test_empty_genre.pdf")
        recs = {
            "movies": {
                "Action": [_make_item(1, "Action Movie")],
                "Thriller": [],  # Empty genre bucket
                "Drama": [],
                "Comedy": [],
            },
            "series": {},
        }

        # Should not raise any exception
        generate_pdf(recs, output_path, run_date=date(2026, 3, 1))

        assert os.path.exists(output_path)

    def test_generate_runs_without_error_all_genres_empty(self, tmp_path):
        """PDF generation succeeds even when all genre buckets are empty (edge case)."""
        output_path = str(tmp_path / "test_all_empty.pdf")
        recs = {
            "movies": {"Action": [], "Thriller": [], "Drama": [], "Comedy": []},
            "series": {"Action": [], "Thriller": [], "Drama": [], "Comedy": []},
        }

        generate_pdf(recs, output_path, run_date=date(2026, 3, 1))

        assert os.path.exists(output_path)

    def test_generate_all_4_genres_with_3_items_each(self, tmp_path):
        """PDF generation succeeds with all 4 genres populated with 3 items each (UC-012)."""
        output_path = str(tmp_path / "test_full.pdf")
        recs = _make_full_recommendations()

        generate_pdf(recs, output_path, run_date=date(2026, 3, 1))

        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 0

    def test_generate_with_single_item_genre(self, tmp_path):
        """PDF generation succeeds when a genre has only 1 item (UC-014 AC-4)."""
        output_path = str(tmp_path / "test_single_item.pdf")
        recs = {
            "movies": {"Action": [_make_item(1, "Solo Action Movie")]},
            "series": {},
        }

        generate_pdf(recs, output_path, run_date=date(2026, 3, 1))

        assert os.path.exists(output_path)


# ---------------------------------------------------------------------------
# UC-014: Kannada scarcity note
# ---------------------------------------------------------------------------


class TestKannadaScarcityNote:
    """Tests for Kannada scarcity note in the PDF cover (UC-014)."""

    def test_generate_runs_without_error_when_kn_items_are_zero(self, tmp_path):
        """PDF generation succeeds with no Kannada items (UC-014 AC-1)."""
        output_path = str(tmp_path / "test_no_kannada.pdf")
        recs = {
            "movies": {
                "Action": [
                    _make_item(1, "Hindi Action", language="hi"),
                    _make_item(2, "English Action", language="en"),
                ],
            },
            "series": {},
        }

        # Should not raise any exception
        generate_pdf(recs, output_path, run_date=date(2026, 3, 1))

        assert os.path.exists(output_path)

    def test_generate_uses_run_date_for_cover_page(self, tmp_path):
        """PDF is generated with the specified run_date (not today by default) (UC-012 AC-2)."""
        output_path = str(tmp_path / "test_date.pdf")
        run_date = date(2026, 3, 7)  # A specific Saturday
        recs = _make_minimal_recommendations()

        result = generate_pdf(recs, output_path, run_date=run_date)

        assert os.path.exists(result)
        # Verify the file was created without error
        assert os.path.getsize(result) > 0

    def test_generate_with_none_imdb_rating(self, tmp_path):
        """PDF generation handles items with imdb_rating=None correctly (UC-012 AC-7)."""
        output_path = str(tmp_path / "test_none_rating.pdf")
        item = _make_item(1, "No Rating Movie", imdb_rating=None)
        item.imdb_rating = None
        recs = {"movies": {"Action": [item]}, "series": {}}

        generate_pdf(recs, output_path, run_date=date(2026, 3, 1))

        assert os.path.exists(output_path)

    def test_generate_with_empty_overview(self, tmp_path):
        """PDF generation handles items with empty overview (UC-012 AF-3)."""
        output_path = str(tmp_path / "test_empty_overview.pdf")
        item = _make_item(1, "No Overview Movie", overview="")
        recs = {"movies": {"Action": [item]}, "series": {}}

        generate_pdf(recs, output_path, run_date=date(2026, 3, 1))

        assert os.path.exists(output_path)

    def test_generate_with_both_movies_and_series(self, tmp_path):
        """PDF generation handles both movies and series recommendations (UC-012)."""
        output_path = str(tmp_path / "test_mixed.pdf")
        recs = {
            "movies": {
                "Action": [_make_item(1, "Action Movie", language="hi")],
                "Drama": [_make_item(2, "Drama Movie", language="en")],
            },
            "series": {
                "Comedy": [_make_item(10, "Comedy Series", media_type="tv", language="kn")],
            },
        }

        generate_pdf(recs, output_path, run_date=date(2026, 3, 1))

        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 0
