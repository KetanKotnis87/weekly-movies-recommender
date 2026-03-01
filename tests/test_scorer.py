"""
Tests for src/scorer.py

Covers: UC-004, UC-005, UC-006, UC-007, UC-008, UC-014

All tests are self-contained with no shared mutable state.
"""

import math
from datetime import date, timedelta

import pytest

from src.scorer import (
    ContentItem,
    bucket_by_genre,
    deduplicate_across_genres,
    filter_by_language,
    filter_by_ott,
    filter_by_recency,
    filter_by_vote_count,
    pre_select_candidates,
    rank_and_select,
    score_item,
)


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
    overview: str = "A test overview.",
    spoken_languages: list = None,
):
    """Create a minimal ContentItem for testing."""
    if genres is None:
        genres = ["Action"]
    if release_date is None:
        release_date = (date.today() - timedelta(days=100)).strftime("%Y-%m-%d")
    if ott_platforms is None:
        ott_platforms = ["Netflix"]
    if spoken_languages is None:
        spoken_languages = [language]

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
        poster_path=f"/{title}.jpg",
        ott_platforms=ott_platforms,
        spoken_languages=spoken_languages,
    )
    item.score = score_item(item)
    return item


# ---------------------------------------------------------------------------
# filter_by_language — UC-004
# ---------------------------------------------------------------------------


class TestFilterByLanguage:
    """Tests for filter_by_language function (UC-004)."""

    def test_filter_keeps_hindi_english_kannada(self):
        """Retains items in hi, en, kn languages (UC-004 AC-1, AC-3)."""
        items = [
            _make_item(1, "Hindi Movie", language="hi"),
            _make_item(2, "English Movie", language="en"),
            _make_item(3, "Kannada Movie", language="kn"),
        ]
        result = filter_by_language(items)

        assert len(result) == 3
        languages = {item.language for item in result}
        assert languages == {"hi", "en", "kn"}

    def test_filter_keeps_tamil_content(self):
        """Tamil (ta) is now a supported South Indian language (UC-004)."""
        items = [
            _make_item(1, "Tamil Movie", language="ta"),
            _make_item(2, "English Movie", language="en"),
        ]
        result = filter_by_language(items)

        assert len(result) == 2

    def test_filter_keeps_telugu_content(self):
        """Telugu (te) is now a supported South Indian language."""
        items = [
            _make_item(1, "Telugu Movie", language="te"),
        ]
        result = filter_by_language(items)
        assert len(result) == 1

    def test_filter_keeps_malayalam_content(self):
        """Malayalam (ml) is now a supported South Indian language."""
        items = [
            _make_item(1, "Malayalam Movie", language="ml"),
        ]
        result = filter_by_language(items)
        assert len(result) == 1

    def test_filter_drops_unsupported_language_without_dub(self):
        """Japanese content with no Hindi/English/Kannada dub is dropped."""
        items = [
            _make_item(1, "Japanese Movie", language="ja", spoken_languages=["ja"]),
        ]
        result = filter_by_language(items)
        assert result == []

    def test_filter_keeps_foreign_content_with_hindi_dub(self):
        """Korean movie dubbed in Hindi passes the language filter."""
        items = [
            _make_item(1, "Korean Movie", language="ko", spoken_languages=["ko", "hi"]),
        ]
        result = filter_by_language(items)
        assert len(result) == 1

    def test_filter_empty_list_returns_empty(self):
        """Empty input returns empty output without error (UC-004 AF-3)."""
        result = filter_by_language([])
        assert result == []

    def test_filter_custom_languages_parameter(self):
        """Custom languages parameter is respected — only items whose original
        language is in the custom list pass (spoken_languages dub check uses
        DUB_LANGUAGES, not the custom list)."""
        items = [
            _make_item(1, "Tamil Movie", language="ta", spoken_languages=["ta"]),
            _make_item(2, "Telugu Movie", language="te", spoken_languages=["te"]),
        ]
        result = filter_by_language(items, languages=["ta"])

        assert len(result) == 1
        assert result[0].language == "ta"

    def test_filter_mixed_languages_returns_only_permitted(self):
        """Only supported language items are retained from a mixed list."""
        items = [
            _make_item(1, "Hindi Movie", language="hi"),
            _make_item(2, "French Movie", language="fr"),
            _make_item(3, "Spanish Movie", language="es"),
            _make_item(4, "Kannada Movie", language="kn"),
        ]
        result = filter_by_language(items)

        assert len(result) == 2
        languages = {item.language for item in result}
        assert languages == {"hi", "kn"}


# ---------------------------------------------------------------------------
# filter_by_recency — UC-006
# ---------------------------------------------------------------------------


class TestFilterByRecency:
    """Tests for filter_by_recency function (UC-006)."""

    def test_filter_keeps_items_within_365_days(self):
        """Items released within 365 days are retained (UC-006 AC-4)."""
        items = [
            _make_item(1, "Recent Movie", release_date=(date.today() - timedelta(days=100)).strftime("%Y-%m-%d")),
        ]
        result = filter_by_recency(items)
        assert len(result) == 1

    def test_filter_drops_items_older_than_365_days(self):
        """Items older than 365 days are excluded (UC-006 AC-2)."""
        items = [
            _make_item(1, "Old Movie", release_date=(date.today() - timedelta(days=400)).strftime("%Y-%m-%d")),
        ]
        result = filter_by_recency(items)
        assert len(result) == 0

    def test_filter_keeps_item_exactly_365_days_old(self):
        """An item exactly 365 days old is retained (inclusive boundary, UC-006 AC-1)."""
        items = [
            _make_item(1, "Boundary Movie", release_date=(date.today() - timedelta(days=365)).strftime("%Y-%m-%d")),
        ]
        result = filter_by_recency(items)
        assert len(result) == 1

    def test_filter_drops_item_366_days_old(self):
        """An item 366 days old is excluded (UC-006 AC-2)."""
        items = [
            _make_item(1, "Just Old Movie", release_date=(date.today() - timedelta(days=366)).strftime("%Y-%m-%d")),
        ]
        result = filter_by_recency(items)
        assert len(result) == 0

    def test_filter_excludes_item_with_empty_release_date(self):
        """Items with empty release_date are excluded (UC-006 AF-1)."""
        item = _make_item(1, "No Date Movie")
        item.release_date = ""
        result = filter_by_recency([item])
        assert len(result) == 0

    def test_filter_excludes_item_with_missing_release_date(self):
        """Items with None release_date are excluded."""
        item = _make_item(1, "No Date Movie")
        item.release_date = None
        result = filter_by_recency([item])
        assert len(result) == 0

    def test_filter_excludes_item_with_unparseable_date(self):
        """Items with unparseable date strings are excluded (UC-006 AF-2)."""
        item = _make_item(1, "Bad Date Movie")
        item.release_date = "not-a-date"
        result = filter_by_recency([item])
        assert len(result) == 0

    def test_filter_empty_list_returns_empty(self):
        """Empty input returns empty output."""
        result = filter_by_recency([])
        assert result == []

    def test_filter_custom_days_parameter(self):
        """Custom days parameter is respected."""
        items = [
            _make_item(1, "Recent 30 days", release_date=(date.today() - timedelta(days=30)).strftime("%Y-%m-%d")),
            _make_item(2, "Recent 50 days", release_date=(date.today() - timedelta(days=50)).strftime("%Y-%m-%d")),
        ]
        result = filter_by_recency(items, days=40)

        assert len(result) == 1
        assert result[0].title == "Recent 30 days"


# ---------------------------------------------------------------------------
# filter_by_vote_count — UC-008 / UC-007
# ---------------------------------------------------------------------------


class TestFilterByVoteCount:
    """Tests for filter_by_vote_count function."""

    def test_filter_drops_items_below_min_vote_count(self):
        """Drops items with vote_count < 50 (MIN_VOTE_COUNT) (UC-008)."""
        items = [
            _make_item(1, "Low Votes Movie", vote_count=49),
            _make_item(2, "Enough Votes Movie", vote_count=50),
            _make_item(3, "High Votes Movie", vote_count=10000),
        ]
        result = filter_by_vote_count(items)

        assert len(result) == 2
        vote_counts = [item.vote_count for item in result]
        assert 49 not in vote_counts

    def test_filter_keeps_items_at_exactly_min_vote_count(self):
        """Items with exactly MIN_VOTE_COUNT (50) votes are retained."""
        items = [_make_item(1, "Exact Min Votes", vote_count=50)]
        result = filter_by_vote_count(items)
        assert len(result) == 1

    def test_filter_empty_list_returns_empty(self):
        """Empty input returns empty output."""
        result = filter_by_vote_count([])
        assert result == []

    def test_filter_custom_min_count(self):
        """Custom min_count parameter is respected."""
        items = [
            _make_item(1, "Movie 100 votes", vote_count=100),
            _make_item(2, "Movie 500 votes", vote_count=500),
        ]
        result = filter_by_vote_count(items, min_count=200)

        assert len(result) == 1
        assert result[0].vote_count == 500


# ---------------------------------------------------------------------------
# filter_by_ott
# ---------------------------------------------------------------------------


class TestFilterByOtt:
    """Tests for filter_by_ott function."""

    def test_filter_drops_items_with_no_ott_platforms(self):
        """Drops items with empty ott_platforms list (UC-010 filter)."""
        items = [
            _make_item(1, "On Netflix", ott_platforms=["Netflix"]),
            _make_item(2, "Not on OTT", ott_platforms=[]),
        ]
        result = filter_by_ott(items)

        assert len(result) == 1
        assert result[0].title == "On Netflix"

    def test_filter_keeps_items_with_ott_platforms(self):
        """Retains items with at least one OTT platform."""
        items = [
            _make_item(1, "On Netflix", ott_platforms=["Netflix"]),
            _make_item(2, "On Prime", ott_platforms=["Amazon Prime Video"]),
        ]
        result = filter_by_ott(items)
        assert len(result) == 2

    def test_filter_empty_list_returns_empty(self):
        """Empty input returns empty output."""
        result = filter_by_ott([])
        assert result == []


# ---------------------------------------------------------------------------
# score_item — UC-007
# ---------------------------------------------------------------------------


class TestScoreItem:
    """Tests for the composite scoring formula (UC-007)."""

    def test_score_item_canonical_test_case(self):
        """
        Verify canonical test case with V2 weights (0.45/0.20/0.15/0.10/0.10).
        tmdb_popularity=100.0, imdb_rating=7.5, vote_count=10000,
        google_trends_score=None, youtube_views=None (both default to 0).

        Expected: (7.5/10)*0.45 + (100.0/200)*0.20 + (5000/5000)*0.15 + 0 + 0
                = 0.3375 + 0.10 + 0.15
                = 0.5875
        """
        item = _make_item(1, "Test Movie", popularity=100.0, imdb_rating=7.5, vote_count=10000)
        score = score_item(item)

        expected_rating = (7.5 / 10) * 0.45
        expected_popularity = (min(100.0, 200) / 200) * 0.20
        expected_votes = (min(10000, 5000) / 5000) * 0.15
        expected = round(expected_rating + expected_popularity + expected_votes, 4)

        assert abs(score - expected) < 0.001
        # Verify approximately 0.5875 with V2 weights
        assert 0.58 < score < 0.60

    def test_score_item_imdb_rating_zero_produces_valid_score(self):
        """imdb_rating=0 (not None) still produces a valid, non-negative score (UC-007 AC-2)."""
        item = _make_item(1, "Test Movie", popularity=50.0, imdb_rating=0.0, vote_count=1000)
        item.imdb_rating = 0.0
        score = score_item(item)

        assert score >= 0.0
        assert isinstance(score, float)

    def test_score_item_imdb_rating_none_does_not_raise(self):
        """imdb_rating=None produces valid score without exception (UC-007 AC-2)."""
        item = _make_item(1, "Test Movie", popularity=100.0, imdb_rating=None, vote_count=1000)
        item.imdb_rating = None
        score = score_item(item)

        assert score >= 0.0
        assert isinstance(score, float)
        # With None, rating component = 0; V2 signals also default to 0 (None fields)
        expected = round(
            0.0
            + (min(100.0, 200) / 200) * 0.20
            + (min(1000, 5000) / 5000) * 0.15,
            4,
        )
        assert abs(score - expected) < 0.001

    def test_score_item_zero_votes_uses_log10_of_one(self):
        """vote_count=0 contributes 0 to the score (min(0,5000)/5000 = 0) (UC-007 AF-2)."""
        item = _make_item(1, "No Votes Movie", popularity=100.0, imdb_rating=7.0, vote_count=0)
        item.vote_count = 0
        score = score_item(item)

        # V2 formula: votes_component = 0 when vote_count=0; V2 signals default to 0
        expected = round(
            (7.0 / 10) * 0.45
            + (min(100.0, 200) / 200) * 0.20
            + 0.0,
            4,
        )
        assert abs(score - expected) < 0.001

    def test_score_item_higher_popularity_yields_higher_score(self):
        """Items with higher TMDB popularity get a higher composite score."""
        low_pop = _make_item(1, "Low Pop", popularity=10.0, imdb_rating=7.0, vote_count=1000)
        high_pop = _make_item(2, "High Pop", popularity=200.0, imdb_rating=7.0, vote_count=1000)

        assert score_item(high_pop) > score_item(low_pop)

    def test_score_rounded_to_4_decimal_places(self):
        """Score is rounded to exactly 4 decimal places."""
        item = _make_item(1, "Test Movie", popularity=123.456, imdb_rating=7.3, vote_count=5678)
        score = score_item(item)

        # Check that it's a float with at most 4 decimal places
        assert score == round(score, 4)


# ---------------------------------------------------------------------------
# rank_and_select — UC-008
# ---------------------------------------------------------------------------


class TestRankAndSelect:
    """Tests for rank_and_select function (UC-008)."""

    def test_rank_and_select_returns_top_3_sorted_by_score_desc(self):
        """Returns top 3 items sorted by score descending (UC-008 AC-1)."""
        items = [
            _make_item(1, "Score 5", popularity=10.0, imdb_rating=5.0, vote_count=100),
            _make_item(2, "Score 8", popularity=10.0, imdb_rating=8.0, vote_count=100),
            _make_item(3, "Score 7", popularity=10.0, imdb_rating=7.0, vote_count=100),
            _make_item(4, "Score 9", popularity=10.0, imdb_rating=9.0, vote_count=100),
            _make_item(5, "Score 6", popularity=10.0, imdb_rating=6.0, vote_count=100),
        ]
        result = rank_and_select(items, genre="Action")

        assert len(result) == 3
        # Should be sorted: score_9 > score_8 > score_7
        assert result[0].title == "Score 9"
        assert result[1].title == "Score 8"
        assert result[2].title == "Score 7"

    def test_rank_and_select_returns_fewer_than_3_if_insufficient(self):
        """Returns all available items if fewer than 3 exist (UC-008 AF-2, UC-014 AC-4)."""
        items = [
            _make_item(1, "Only Movie", popularity=100.0),
        ]
        result = rank_and_select(items, genre="Action")

        assert len(result) == 1

    def test_rank_and_select_returns_two_when_two_available(self):
        """Returns exactly 2 items when only 2 qualify (UC-008 AC-2)."""
        items = [
            _make_item(1, "Movie A", popularity=100.0),
            _make_item(2, "Movie B", popularity=80.0),
        ]
        result = rank_and_select(items, genre="Action")
        assert len(result) == 2

    def test_rank_and_select_empty_input_returns_empty(self):
        """Empty input returns empty list without error (UC-008 AF-1)."""
        result = rank_and_select([], genre="Action")
        assert result == []

    def test_rank_and_select_respects_top_n_parameter(self):
        """Custom top_n parameter limits the result count."""
        items = [_make_item(i, f"Movie {i}", popularity=float(100 - i)) for i in range(1, 6)]
        result = rank_and_select(items, genre="Action", top_n=2)
        assert len(result) == 2

    def test_rank_and_select_tiebreak_by_popularity(self):
        """Ties in score are broken by higher tmdb_popularity (UC-007 AF-4)."""
        # Create two items with the same score by using identical parameters
        item1 = _make_item(1, "B Movie", popularity=200.0, imdb_rating=7.0, vote_count=1000)
        item2 = _make_item(2, "A Movie", popularity=100.0, imdb_rating=7.0, vote_count=1000)
        # Force same score
        item1.score = 50.0
        item2.score = 50.0

        result = rank_and_select([item1, item2], genre="Action")

        # Higher popularity (item1 with 200.0) should come first
        assert result[0].id == 1


# ---------------------------------------------------------------------------
# bucket_by_genre — UC-005 / UC-008
# ---------------------------------------------------------------------------


class TestBucketByGenre:
    """Tests for bucket_by_genre function."""

    def test_bucket_by_genre_groups_items_correctly(self):
        """Items are grouped into correct genre buckets (UC-005)."""
        items = [
            _make_item(1, "Action Movie", genres=["Action"]),
            _make_item(2, "Drama Movie", genres=["Drama"]),
            _make_item(3, "Comedy Movie", genres=["Comedy"]),
            _make_item(4, "Thriller Movie", genres=["Thriller"]),
        ]
        buckets = bucket_by_genre(items)

        assert len(buckets["Action"]) == 1
        assert len(buckets["Drama"]) == 1
        assert len(buckets["Comedy"]) == 1
        assert len(buckets["Thriller"]) == 1
        assert buckets["Action"][0].title == "Action Movie"

    def test_bucket_by_genre_multi_genre_item_appears_in_multiple_buckets(self):
        """An item with multiple genres appears in all matching buckets before dedup."""
        items = [
            _make_item(1, "Action Drama", genres=["Action", "Drama"]),
        ]
        buckets = bucket_by_genre(items)

        assert len(buckets["Action"]) == 1
        assert len(buckets["Drama"]) == 1
        assert buckets["Action"][0].id == 1
        assert buckets["Drama"][0].id == 1

    def test_bucket_by_genre_all_genre_keys_present(self):
        """All 4 genre keys are present in the result dict even if empty."""
        buckets = bucket_by_genre([])

        assert "Action" in buckets
        assert "Thriller" in buckets
        assert "Drama" in buckets
        assert "Comedy" in buckets

    def test_bucket_by_genre_empty_input_returns_empty_buckets(self):
        """Empty input returns all genre keys with empty lists."""
        buckets = bucket_by_genre([])
        for genre in ["Action", "Thriller", "Drama", "Comedy"]:
            assert buckets[genre] == []


# ---------------------------------------------------------------------------
# deduplicate_across_genres — UC-008
# ---------------------------------------------------------------------------


class TestDeduplicateAcrossGenres:
    """Tests for deduplicate_across_genres function (UC-008)."""

    def test_deduplicate_item_appears_in_exactly_one_genre_bucket(self):
        """After deduplication, each item appears in exactly one bucket (UC-008 AC-3)."""
        item = _make_item(1, "Multi-Genre Movie", genres=["Action", "Drama"])
        item.score = 85.0

        buckets = {
            "Action": [item],
            "Thriller": [],
            "Drama": [item],
            "Comedy": [],
        }
        deduped = deduplicate_across_genres(buckets)

        total_occurrences = sum(
            1 for genre_items in deduped.values() for i in genre_items if i.id == item.id
        )
        assert total_occurrences == 1

    def test_deduplicate_item_assigned_to_highest_scoring_genre(self):
        """Item is kept in the genre where it has the highest score."""
        item1 = _make_item(1, "Shared Movie", genres=["Action"])
        item1.score = 90.0
        item2 = _make_item(1, "Shared Movie", genres=["Drama"])
        item2.score = 95.0  # Higher score in Drama

        # Same TMDB ID but different score instances in different buckets
        buckets = {
            "Action": [item1],
            "Thriller": [],
            "Drama": [item2],
            "Comedy": [],
        }
        deduped = deduplicate_across_genres(buckets)

        # Item should appear only in Drama (higher score)
        assert any(i.id == 1 for i in deduped["Drama"])
        assert not any(i.id == 1 for i in deduped["Action"])

    def test_deduplicate_canonical_order_tiebreak(self):
        """Tie in score: first genre in canonical order wins (Action > Thriller > Drama > Comedy)."""
        item_action = _make_item(1, "Tie Movie", genres=["Action"])
        item_action.score = 75.0
        item_comedy = _make_item(1, "Tie Movie", genres=["Comedy"])
        item_comedy.score = 75.0  # Same score

        buckets = {
            "Action": [item_action],
            "Thriller": [],
            "Drama": [],
            "Comedy": [item_comedy],
        }
        deduped = deduplicate_across_genres(buckets)

        # Action should win (earlier in canonical order)
        assert any(i.id == 1 for i in deduped["Action"])
        assert not any(i.id == 1 for i in deduped["Comedy"])

    def test_deduplicate_no_cross_genre_duplicates_in_output(self):
        """No item ID appears in more than one bucket after deduplication."""
        items = [
            _make_item(1, "Action Movie", genres=["Action"]),
            _make_item(2, "Drama Movie", genres=["Drama"]),
            _make_item(3, "Multi Genre", genres=["Action", "Comedy"]),
        ]
        items[2].score = 80.0

        buckets = bucket_by_genre(items)
        deduped = deduplicate_across_genres(buckets)

        seen_ids = set()
        for genre_items in deduped.values():
            for item in genre_items:
                assert item.id not in seen_ids, f"Duplicate item ID {item.id} found in multiple genres"
                seen_ids.add(item.id)


# ---------------------------------------------------------------------------
# Kannada scarcity handling — UC-014
# ---------------------------------------------------------------------------


class TestKannadaScarcity:
    """Tests for Kannada content handling (UC-014)."""

    def test_rank_and_select_with_zero_kn_items_returns_best_available(self):
        """When no Kannada items exist in a genre, returns best available (UC-014 AC-1)."""
        # Simulate a genre bucket with only Hindi and English items
        items = [
            _make_item(1, "Hindi Drama", language="hi", genres=["Drama"], popularity=100.0),
            _make_item(2, "English Drama", language="en", genres=["Drama"], popularity=80.0),
        ]
        result = rank_and_select(items, genre="Drama")

        # Should return items without crashing (no Kannada required)
        assert len(result) == 2
        assert result[0].language in {"hi", "en"}

    def test_filter_by_language_empty_kn_does_not_crash(self):
        """Language filter with no Kannada items does not crash (UC-014 AF-1)."""
        items = [
            _make_item(1, "Hindi Movie", language="hi"),
            _make_item(2, "English Movie", language="en"),
        ]
        result = filter_by_language(items)

        # Should succeed with no Kannada items
        assert len(result) == 2
        assert not any(item.language == "kn" for item in result)

    def test_all_genre_buckets_work_with_zero_kn_items(self):
        """bucket_by_genre and rank_and_select work with no Kannada items in any genre (UC-014)."""
        items = [
            _make_item(1, "Hindi Action", language="hi", genres=["Action"]),
            _make_item(2, "English Drama", language="en", genres=["Drama"]),
        ]
        buckets = bucket_by_genre(items)
        deduped = deduplicate_across_genres(buckets)

        # rank_and_select should work for each genre without crashing
        for genre in ["Action", "Thriller", "Drama", "Comedy"]:
            genre_items = deduped.get(genre, [])
            if genre_items:
                result = rank_and_select(genre_items, genre=genre)
                assert isinstance(result, list)


# ---------------------------------------------------------------------------
# V2 scoring tests — UC-020 (5-signal formula with graceful degradation)
# ---------------------------------------------------------------------------


class TestScoreItemV2Signals:
    """
    Tests for the V2 5-signal composite score formula with Google Trends
    and YouTube signals.  Covers UC-020 degradation behaviour.
    """

    def test_score_item_with_trends_signal(self):
        """
        UC-020 AC-5: A title with google_trends_score=80.0 and youtube_views=None
        contributes (80/100)*0.10 = 0.08 extra over the 3-signal baseline.
        """
        # Build a baseline item (no V2 signals)
        baseline = _make_item(1, "Baseline", popularity=100.0, imdb_rating=7.5, vote_count=5000)
        baseline_score = score_item(baseline)

        # Add Trends signal only
        item_with_trends = _make_item(2, "WithTrends", popularity=100.0, imdb_rating=7.5, vote_count=5000)
        item_with_trends.google_trends_score = 80.0
        item_with_trends.youtube_views = None
        trends_score = score_item(item_with_trends)

        expected_trends_contribution = (80.0 / 100) * 0.10
        assert abs(trends_score - (baseline_score + expected_trends_contribution)) < 1e-4

    def test_score_item_with_youtube_signal(self):
        """
        UC-020 AC-5: A title with youtube_views=5_000_000 and google_trends_score=None
        contributes (5M/10M)*0.10 = 0.05 extra over the 3-signal baseline.
        """
        baseline = _make_item(1, "Baseline", popularity=100.0, imdb_rating=7.5, vote_count=5000)
        baseline_score = score_item(baseline)

        item_with_yt = _make_item(2, "WithYT", popularity=100.0, imdb_rating=7.5, vote_count=5000)
        item_with_yt.google_trends_score = None
        item_with_yt.youtube_views = 5_000_000
        yt_score = score_item(item_with_yt)

        expected_yt_contribution = (min(5_000_000, 10_000_000) / 10_000_000) * 0.10
        assert abs(yt_score - (baseline_score + expected_yt_contribution)) < 1e-4

    def test_score_item_with_both_v2_signals(self):
        """
        UC-020 (5-signal formula): With both V2 signals set, all 5 components
        sum correctly and the score is within the expected range.
        """
        item = _make_item(3, "FullSignal", popularity=100.0, imdb_rating=7.5, vote_count=5000)
        item.google_trends_score = 80.0
        item.youtube_views = 5_000_000

        result = score_item(item)

        rating_c    = (7.5 / 10) * 0.45
        pop_c       = (min(100.0, 200) / 200) * 0.20
        votes_c     = (min(5000, 5000) / 5000) * 0.15
        trends_c    = (80.0 / 100) * 0.10
        youtube_c   = (min(5_000_000, 10_000_000) / 10_000_000) * 0.10
        expected = round(rating_c + pop_c + votes_c + trends_c + youtube_c, 4)

        assert abs(result - expected) < 1e-4

    def test_score_item_degrades_to_v1_when_signals_none(self):
        """
        UC-020 AC-3: When both V2 signals are None, the score equals the
        3-signal result (Trends and YouTube contribute 0.0 each).
        The score must be identical whether we set both to None explicitly
        or leave them at their default.
        """
        item_default = _make_item(1, "Default", popularity=150.0, imdb_rating=8.0, vote_count=3000)
        # google_trends_score and youtube_views are None by default in _make_item

        item_explicit_none = _make_item(2, "ExplicitNone", popularity=150.0, imdb_rating=8.0, vote_count=3000)
        item_explicit_none.google_trends_score = None
        item_explicit_none.youtube_views = None

        score_default = score_item(item_default)
        score_explicit = score_item(item_explicit_none)

        assert score_default == score_explicit

    def test_score_item_youtube_views_capped_at_10_million(self):
        """
        YouTube views are capped at 10M; 50M views yields the same contribution as 10M.
        """
        item_10m = _make_item(1, "10M Views", popularity=100.0, imdb_rating=7.0, vote_count=1000)
        item_10m.youtube_views = 10_000_000

        item_50m = _make_item(2, "50M Views", popularity=100.0, imdb_rating=7.0, vote_count=1000)
        item_50m.youtube_views = 50_000_000

        assert score_item(item_10m) == score_item(item_50m)

    def test_score_item_trends_score_zero_adds_nothing(self):
        """
        A google_trends_score of 0 (valid data, but zero interest) contributes
        exactly 0.0 to the score — same as None.
        """
        item_none = _make_item(1, "NoTrends", popularity=100.0, imdb_rating=7.0, vote_count=1000)
        item_none.google_trends_score = None

        item_zero = _make_item(2, "ZeroTrends", popularity=100.0, imdb_rating=7.0, vote_count=1000)
        item_zero.google_trends_score = 0.0

        assert score_item(item_none) == score_item(item_zero)

    def test_score_maximum_possible_is_1_0(self):
        """
        With all signals at their maximum values, the score is exactly 1.0.
        """
        item = _make_item(1, "Perfect", popularity=200.0, imdb_rating=10.0, vote_count=5000)
        item.google_trends_score = 100.0
        item.youtube_views = 10_000_000

        assert score_item(item) == 1.0


# ---------------------------------------------------------------------------
# pre_select_candidates tests — UC-018
# ---------------------------------------------------------------------------


class TestPreSelectCandidates:
    """
    Tests for pre_select_candidates() — UC-018.

    Note: pre_select_candidates() operates on a flat list and selects the
    top (top_n * multiplier) items globally.  The test suite validates the
    function's contract as implemented; the per-genre-bucket logic defect
    (HIGH-001) is corroborated separately.
    """

    def test_pre_select_returns_top_n_times_multiplier(self):
        """
        UC-018 AC-1 analogue: given 20 items, top_n=3, multiplier=2 → 6 returned.
        """
        items = [
            _make_item(i, f"Movie {i}", popularity=float(100 - i), imdb_rating=7.0, vote_count=1000)
            for i in range(1, 21)  # 20 items
        ]
        # Assign scores so they are differentiable
        for item in items:
            item.score = score_item(item)

        result = pre_select_candidates(items, top_n=3, multiplier=2)

        assert len(result) == 6

    def test_pre_select_returns_all_when_fewer_than_pool(self):
        """
        UC-018 AF-1: When total items (4) < pool size (6), all 4 are returned.
        """
        items = [
            _make_item(i, f"Movie {i}", popularity=float(100 - i), imdb_rating=7.0, vote_count=1000)
            for i in range(1, 5)  # only 4 items
        ]
        for item in items:
            item.score = score_item(item)

        result = pre_select_candidates(items, top_n=3, multiplier=2)

        assert len(result) == 4

    def test_pre_select_sorted_by_score_desc(self):
        """
        UC-018 Main Flow step 3: The returned list is sorted by score descending;
        the highest-scored item is first.
        """
        # Deliberately create items with decreasing scores
        low  = _make_item(1, "Low Score",  popularity=10.0,  imdb_rating=5.0, vote_count=100)
        mid  = _make_item(2, "Mid Score",  popularity=50.0,  imdb_rating=7.0, vote_count=1000)
        high = _make_item(3, "High Score", popularity=150.0, imdb_rating=9.0, vote_count=5000)

        for item in [low, mid, high]:
            item.score = score_item(item)

        result = pre_select_candidates([low, mid, high], top_n=3, multiplier=2)

        assert result[0].title == "High Score"

    def test_pre_select_returns_empty_on_empty_input(self):
        """Edge case: empty input produces empty output."""
        result = pre_select_candidates([], top_n=3, multiplier=2)
        assert result == []

    def test_pre_select_pool_size_is_top_n_times_multiplier(self):
        """
        The pool_size = top_n * multiplier contract: with top_n=5, multiplier=3,
        pool_size=15; given 20 items, exactly 15 are returned.
        """
        items = [
            _make_item(i, f"Film {i}", popularity=float(200 - i), imdb_rating=7.0, vote_count=1000)
            for i in range(1, 21)  # 20 items
        ]
        for item in items:
            item.score = score_item(item)

        result = pre_select_candidates(items, top_n=5, multiplier=3)

        assert len(result) == 15

    def test_pre_select_tiebreak_by_popularity_then_title(self):
        """
        UC-018 AF-3 tiebreak: items with identical scores are broken by
        higher tmdb_popularity, then alphabetically by title.
        """
        # Force identical scores by using identical parameters
        item_z = _make_item(1, "Z Film", popularity=200.0, imdb_rating=7.0, vote_count=1000)
        item_a = _make_item(2, "A Film", popularity=100.0, imdb_rating=7.0, vote_count=1000)
        item_m = _make_item(3, "M Film", popularity=200.0, imdb_rating=7.0, vote_count=1000)

        # Force identical raw scores to test tiebreaking
        item_z.score = 0.5000
        item_a.score = 0.5000
        item_m.score = 0.5000

        # With pool_size=2, tiebreak: popularity 200 (Z Film, M Film) beat popularity 100 (A Film)
        result = pre_select_candidates([item_z, item_a, item_m], top_n=1, multiplier=2)

        assert len(result) == 2
        result_titles = {item.title for item in result}
        assert "A Film" not in result_titles
