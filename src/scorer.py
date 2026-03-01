"""
Scorer module for the Weekly Movie & Web Series Recommender.

Provides:
- ContentItem dataclass: unified representation for a scored movie or TV series.
- Filter functions: language, recency, OTT availability, vote count.
- Scoring function: composite score formula.
- rank_and_select: sorts and selects top-N items per genre.
- bucket_by_genre: groups items into genre buckets.
- Deduplication: ensures each item appears in at most one genre bucket.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.config import (
    DUB_LANGUAGES,
    GENRE_ID_TO_NAME,
    GENRE_ORDER,
    LANGUAGE_CODES,
    MIN_VOTE_COUNT,
    RECENCY_DAYS,
    SUPPORTED_LANGUAGES,
    TOP_N,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ContentItem dataclass
# ---------------------------------------------------------------------------


@dataclass
class ContentItem:
    """
    A unified, scored content item (movie or TV series).

    Attributes:
        id:               TMDB ID.
        title:            Display title.
        media_type:       'movie' or 'tv'.
        genres:           List of qualifying genre names (e.g. ['Action', 'Drama']).
        language:         ISO 639-1 original language code.
        release_date:     Release / first-air date string (YYYY-MM-DD).
        tmdb_popularity:  TMDB popularity float.
        imdb_rating:      IMDB rating (1.0–10.0) or None.
        vote_count:       IMDB vote count (int >= 0).
        overview:         Full TMDB overview string.
        poster_path:      TMDB poster path (e.g. '/abcdef.jpg') or None.
        ott_platforms:    List of confirmed Indian OTT platform names.
        score:            Composite score (computed by score_item()).
        poster_image:     Downloaded image bytes or None.
        imdb_id:          IMDB ID string or None.
    """

    id: int
    title: str
    media_type: str                              # 'movie' or 'tv'
    genres: List[str]                            # qualifying genre name(s)
    language: str                                # original_language ISO code
    release_date: str                            # YYYY-MM-DD
    tmdb_popularity: float
    imdb_rating: Optional[float]
    vote_count: int
    overview: str
    poster_path: Optional[str]
    ott_platforms: List[str] = field(default_factory=list)
    score: float = 0.0
    poster_image: Optional[bytes] = None
    imdb_id: Optional[str] = None
    spoken_languages: List[str] = field(default_factory=list)  # additional spoken language codes

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def language_name(self) -> str:
        """Human-readable language name (e.g. 'Hindi', 'English', 'Kannada')."""
        return LANGUAGE_CODES.get(self.language, self.language.upper())

    @property
    def release_year(self) -> str:
        """4-digit release year extracted from release_date, or '' if unparseable."""
        if self.release_date and len(self.release_date) >= 4:
            return self.release_date[:4]
        return ""

    @property
    def teaser(self) -> str:
        """Overview truncated to 120 chars at a word boundary, with ellipsis."""
        return _truncate_overview(self.overview)


# ---------------------------------------------------------------------------
# Overview truncation helper
# ---------------------------------------------------------------------------


def _truncate_overview(text: str, max_chars: int = 120) -> str:
    """
    Truncate an overview string to at most max_chars characters.

    Cuts at the last word boundary at or before max_chars and appends '...'.

    Args:
        text:      The full overview string.
        max_chars: Maximum character length before truncation.

    Returns:
        The truncated string with '...' appended if it was too long,
        or 'No description available.' if the input is empty/None.
    """
    if not text or not text.strip():
        return "No description available."
    text = text.strip()
    if len(text) <= max_chars:
        return text
    # Find the last space at or before max_chars
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated + "..."


# ---------------------------------------------------------------------------
# Scoring formula
# ---------------------------------------------------------------------------


def score_item(item: ContentItem) -> float:
    """
    Compute the composite score for a ContentItem.

    Formula:
        score = (imdb_rating / 10) * 0.55          # quality signal — highest weight
              + (min(tmdb_popularity, 200) / 200) * 0.25   # buzz signal
              + (min(vote_count, 5000) / 5000) * 0.20      # confidence signal

    All three components are normalised to [0, 1] before weighting, so the
    maximum possible score is 1.0 (when rating=10, popularity>=200, votes>=5000).
    IMDB rating carries the most weight to favour critically acclaimed content
    over viral but poorly rated titles.

    Args:
        item: The ContentItem to score.

    Returns:
        Composite score rounded to 4 decimal places (non-negative float).
    """
    popularity = max(0.0, item.tmdb_popularity or 0.0)
    rating = float(item.imdb_rating) if item.imdb_rating is not None else 0.0
    votes = max(0, item.vote_count or 0)

    rating_component = (rating / 10) * 0.55
    popularity_component = (min(popularity, 200) / 200) * 0.25
    votes_component = (min(votes, 5000) / 5000) * 0.20

    raw_score = rating_component + popularity_component + votes_component
    return round(raw_score, 4)


# ---------------------------------------------------------------------------
# Filter functions
# ---------------------------------------------------------------------------


def filter_by_language(items: List[ContentItem], languages: Optional[List[str]] = None) -> List[ContentItem]:
    """
    Keep items that are accessible in a supported language.

    A title passes if ANY of the following is true:
      1. original_language is in the supported set (hi/en/kn/ta/te/ml).
      2. spoken_languages includes any dub language (hi/en/kn) — catches
         non-Indian content (e.g. Korean, Japanese, French) that has been
         dubbed into Hindi or English for Indian OTT platforms.

    Args:
        items:     List of ContentItem objects to filter.
        languages: Permitted original-language codes. Defaults to SUPPORTED_LANGUAGES.

    Returns:
        Filtered list containing only accessible items.
    """
    if languages is None:
        languages = SUPPORTED_LANGUAGES
    lang_set = set(languages)
    dub_set = set(DUB_LANGUAGES)
    before = len(items)

    def _passes(item: ContentItem) -> bool:
        # Criterion 1: original language is directly supported
        if item.language in lang_set:
            return True
        # Criterion 2: dubbed/translated into Hindi, English, or Kannada
        return any(code in dub_set for code in item.spoken_languages)

    result = [item for item in items if _passes(item)]
    logger.info(
        "Language filter: %s %d -> %d",
        items[0].media_type if items else "items",
        before,
        len(result),
    )
    return result


def filter_by_recency(items: List[ContentItem], days: int = RECENCY_DAYS) -> List[ContentItem]:
    """
    Keep only items released within the last `days` days.

    Items with unparseable or missing release_date are excluded.

    Args:
        items: List of ContentItem objects.
        days:  Maximum age in days (inclusive).

    Returns:
        Filtered list of items within the recency window.
    """
    cutoff: date = date.today() - timedelta(days=days)
    before = len(items)
    result: List[ContentItem] = []

    for item in items:
        raw_date = item.release_date
        if not raw_date:
            logger.debug("Recency: excluded '%s' — missing date.", item.title)
            continue
        try:
            release = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
            if release >= cutoff:
                result.append(item)
            else:
                logger.debug(
                    "Recency: excluded '%s' — %s is %d days old (limit %d).",
                    item.title, release, (date.today() - release).days, days,
                )
        except ValueError:
            logger.debug("Recency: excluded '%s' — unparseable date: '%s'.", item.title, raw_date)

    logger.info(
        "Recency filter: %s %d -> %d",
        items[0].media_type if items else "items",
        before,
        len(result),
    )
    return result


def filter_by_ott(items: List[ContentItem]) -> List[ContentItem]:
    """
    Keep only items that have at least one confirmed Indian OTT platform.

    Args:
        items: List of ContentItem objects.

    Returns:
        Filtered list of items with at least one OTT platform.
    """
    before = len(items)
    result = [item for item in items if item.ott_platforms]
    logger.info(
        "OTT filter: %d -> %d items with confirmed OTT availability.",
        before, len(result),
    )
    return result


def filter_by_vote_count(items: List[ContentItem], min_count: int = MIN_VOTE_COUNT) -> List[ContentItem]:
    """
    Remove items with fewer than min_count IMDB votes to avoid low-sample bias.

    Args:
        items:     List of ContentItem objects.
        min_count: Minimum number of IMDB votes required.

    Returns:
        Filtered list where every item has at least min_count votes.
    """
    before = len(items)
    result = [item for item in items if item.vote_count >= min_count]
    logger.info(
        "Vote count filter (min=%d): %d -> %d items.",
        min_count, before, len(result),
    )
    return result


# ---------------------------------------------------------------------------
# Genre bucketing and deduplication
# ---------------------------------------------------------------------------


def bucket_by_genre(items: List[ContentItem]) -> Dict[str, List[ContentItem]]:
    """
    Group ContentItems into genre buckets based on their 'genres' attribute.

    An item may initially appear in multiple buckets if it qualifies for
    multiple genres. Deduplication is handled by deduplicate_across_genres().

    Args:
        items: List of ContentItem objects, each with 'genres' set.

    Returns:
        Dict mapping genre name -> list of ContentItem objects.
        All genres in GENRE_ORDER are present as keys (possibly empty lists).
    """
    buckets: Dict[str, List[ContentItem]] = {g: [] for g in GENRE_ORDER}
    for item in items:
        for genre in item.genres:
            if genre in buckets:
                buckets[genre].append(item)
    return buckets


def deduplicate_across_genres(
    buckets: Dict[str, List[ContentItem]],
) -> Dict[str, List[ContentItem]]:
    """
    Ensure each item appears in at most one genre bucket.

    If an item qualifies for multiple genres, it is kept only in the bucket
    where it has the highest composite score. Ties are broken by the canonical
    genre order (Action > Thriller > Drama > Comedy).

    Args:
        buckets: Dict mapping genre name -> list of ContentItem objects.
                 Items may be duplicated across buckets at this stage.

    Returns:
        De-duplicated dict where each item appears in exactly one bucket.
    """
    # Map tmdb_id -> (best_genre, best_score) for assignment
    assignment: Dict[int, Tuple[str, float]] = {}

    for genre in GENRE_ORDER:
        for item in buckets.get(genre, []):
            current = assignment.get(item.id)
            if current is None:
                assignment[item.id] = (genre, item.score)
            else:
                prev_genre, prev_score = current
                if item.score > prev_score:
                    assignment[item.id] = (genre, item.score)
                elif item.score == prev_score:
                    # Tiebreak: earlier in GENRE_ORDER wins (already assigned)
                    pass  # keep the first-seen genre

    # Rebuild buckets containing only the assigned genre for each item
    deduped: Dict[str, List[ContentItem]] = {g: [] for g in GENRE_ORDER}
    seen_ids: set = set()

    for genre in GENRE_ORDER:
        for item in buckets.get(genre, []):
            if item.id in seen_ids:
                continue
            assigned_genre, _ = assignment.get(item.id, (genre, 0.0))
            if assigned_genre == genre:
                deduped[genre].append(item)
                seen_ids.add(item.id)

    return deduped


# ---------------------------------------------------------------------------
# Rank and select
# ---------------------------------------------------------------------------


def rank_and_select(
    items: List[ContentItem],
    genre: str,
    top_n: int = TOP_N,
) -> List[ContentItem]:
    """
    Sort items by composite score (descending) and return the top-N.

    Tiebreaking:
        1. Higher tmdb_popularity.
        2. Alphabetically earlier title (ascending).

    Args:
        items:  List of ContentItem objects already in the same genre bucket.
        genre:  Genre name (used only for log messages).
        top_n:  Maximum number of items to return.

    Returns:
        Sorted list of at most top_n ContentItem objects.
    """
    sorted_items = sorted(
        items,
        key=lambda x: (-x.score, -x.tmdb_popularity, x.title.lower()),
    )
    selected = sorted_items[:top_n]
    available = len(items)
    logger.info(
        "Selected %d of %d for %s %s.",
        len(selected), available, genre, items[0].media_type if items else "",
    )
    return selected


# ---------------------------------------------------------------------------
# Build ContentItems from raw data fetcher records
# ---------------------------------------------------------------------------


def build_content_items_from_movies(raw_movies: list) -> List[ContentItem]:
    """
    Convert RawMovie records to ContentItem objects.

    The 'genres' list is derived from genre_ids that intersect with the
    permitted set defined in GENRE_ID_TO_NAME.

    Args:
        raw_movies: List of RawMovie dataclass instances from data_fetcher.

    Returns:
        List of ContentItem objects (score not yet computed).
    """
    items: List[ContentItem] = []
    for raw in raw_movies:
        qualifying_genres = _resolve_genres(raw.genre_ids)
        if not qualifying_genres:
            continue
        item = ContentItem(
            id=raw.id,
            title=raw.title,
            media_type="movie",
            genres=qualifying_genres,
            language=raw.original_language,
            release_date=raw.release_date,
            tmdb_popularity=raw.popularity,
            imdb_rating=raw.imdb_rating,
            vote_count=raw.imdb_vote_count,
            overview=raw.overview,
            poster_path=raw.poster_path,
            ott_platforms=raw.ott_platforms,
            poster_image=raw.poster_image,
            imdb_id=raw.imdb_id,
            spoken_languages=list(raw.spoken_languages),
        )
        item.score = score_item(item)
        items.append(item)
    return items


def build_content_items_from_tv(raw_series: list) -> List[ContentItem]:
    """
    Convert RawTVSeries records to ContentItem objects.

    Args:
        raw_series: List of RawTVSeries dataclass instances from data_fetcher.

    Returns:
        List of ContentItem objects (score computed).
    """
    items: List[ContentItem] = []
    for raw in raw_series:
        qualifying_genres = _resolve_genres(raw.genre_ids)
        if not qualifying_genres:
            continue
        item = ContentItem(
            id=raw.id,
            title=raw.title,
            media_type="tv",
            genres=qualifying_genres,
            language=raw.original_language,
            release_date=raw.first_air_date,
            tmdb_popularity=raw.popularity,
            imdb_rating=raw.imdb_rating,
            vote_count=raw.imdb_vote_count,
            overview=raw.overview,
            poster_path=raw.poster_path,
            ott_platforms=raw.ott_platforms,
            poster_image=raw.poster_image,
            imdb_id=raw.imdb_id,
            spoken_languages=list(raw.spoken_languages),
        )
        item.score = score_item(item)
        items.append(item)
    return items


def _resolve_genres(genre_ids: List[int]) -> List[str]:
    """
    Map a list of TMDB genre IDs to canonical genre names.

    Args:
        genre_ids: List of TMDB numeric genre IDs.

    Returns:
        Deduplicated list of matching canonical genre names (preserving GENRE_ORDER).
    """
    found: List[str] = []
    for gid in genre_ids:
        name = GENRE_ID_TO_NAME.get(gid)
        if name and name not in found:
            found.append(name)
    # Return in canonical order
    return [g for g in GENRE_ORDER if g in found]
