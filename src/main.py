"""
Entry point for the Weekly Movie & Web Series Recommender.

Orchestrates the full pipeline:
  1. Saturday gate (exit on non-Saturday unless --force)
  2. Configuration validation
  3. Fetch trending movies and TV series from TMDB
  4. Language, genre, recency filtering
  5. OMDb enrichment (IMDB rating + vote count)
  6. Watch provider enrichment (Indian OTT platforms)
  7. Poster image download
  8. Scoring, deduplication, top-N selection
  9. PDF generation
  10. Email delivery

CLI flags:
  --dry-run   Run the full pipeline, save PDF locally, skip email.
  --force     Bypass the Saturday gate (useful for testing on any day).

Logging is written to both stdout and a rotating log file.
"""

import argparse
import glob as _glob
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Bootstrap: ensure the project root is on sys.path so src.* imports work
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import (  # noqa: E402
    DISCOVER_LANGUAGES,
    DISCOVER_MOVIE_GENRE_IDS,
    DISCOVER_TV_GENRE_IDS,
    DUB_LANGUAGES,
    GENRE_ORDER,
    PRE_SELECT_MULTIPLIER,
    SUPPORTED_LANGUAGES,
    TOP_N,
    TRENDS_SLEEP_SECONDS,
    load_config,
)
from src.data_fetcher import FatalAPIError, OMDbClient, RawMovie, RawTVSeries, TMDBClient  # noqa: E402
from src.email_sender import send_report  # noqa: E402
from src.pdf_generator import generate_pdf  # noqa: E402
from src.scorer import (  # noqa: E402
    ContentItem,
    bucket_by_genre,
    build_content_items_from_movies,
    build_content_items_from_tv,
    deduplicate_across_genres,
    filter_by_recency,
    pre_select_candidates,
    rank_and_select,
    score_item,
)
from src.trends_fetcher import GoogleTrendsFetcher, YouTubeFetcher  # noqa: E402

# ---------------------------------------------------------------------------
# Log directory and retention settings
# ---------------------------------------------------------------------------

LOG_DIR = PROJECT_ROOT / "logs"
MAX_LOG_FILES = 8                         # NFR-005: retain at most 8 run logs


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(run_date: date) -> logging.Logger:
    """
    Configure root logger with a StreamHandler and a FileHandler.

    Log files are named 'run_YYYY-MM-DD.log' and stored in the logs/ directory.
    After writing, old logs exceeding MAX_LOG_FILES are deleted (NFR-005).

    Args:
        run_date: The execution date (used for log filename).

    Returns:
        The root logger (configured).
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"run_{run_date.isoformat()}.log"

    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    return root_logger


def rotate_logs() -> None:
    """
    Delete oldest log files if there are more than MAX_LOG_FILES in logs/.
    Satisfies NFR-005.
    """
    log_files = sorted(_glob.glob(str(LOG_DIR / "run_*.log")))
    while len(log_files) > MAX_LOG_FILES:
        oldest = log_files.pop(0)
        try:
            os.remove(oldest)
            logging.getLogger(__name__).info("Rotated out old log file: %s", oldest)
        except OSError as exc:
            logging.getLogger(__name__).warning("Could not delete old log %s: %s", oldest, exc)


# ---------------------------------------------------------------------------
# Idempotency helpers (NFR-007 / UC-013 AC-5)
# ---------------------------------------------------------------------------


def _sentinel_path(run_date: date) -> Path:
    """Return the path of the sentinel file that marks a successful email send."""
    return LOG_DIR / f"sent_{run_date.isoformat()}.sentinel"


def _mark_sent(run_date: date) -> None:
    """Write the sentinel file after a successful email send."""
    _sentinel_path(run_date).write_text(
        f"Email sent at {datetime.now().isoformat()}\n", encoding="utf-8"
    )


def _already_sent(run_date: date) -> bool:
    """Return True if the sentinel file for run_date exists."""
    return _sentinel_path(run_date).is_file()


# ---------------------------------------------------------------------------
# PDF output path
# ---------------------------------------------------------------------------


def _pdf_path(run_date: date) -> Path:
    """Return the output path for the PDF report."""
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"movie_recommendations_{run_date.isoformat()}.pdf"


# ---------------------------------------------------------------------------
# Enrichment helpers
# ---------------------------------------------------------------------------


def _enrich_with_imdb(
    raw_movies: List[RawMovie],
    raw_series: List[RawTVSeries],
    tmdb: TMDBClient,
    omdb: OMDbClient,
) -> None:
    """
    Attach IMDB rating and vote count to each raw record in-place.

    Fetches the IMDB ID via TMDB external_ids, then queries OMDb for ratings.

    Args:
        raw_movies:  List of RawMovie records to enrich.
        raw_series:  List of RawTVSeries records to enrich.
        tmdb:        Configured TMDBClient.
        omdb:        Configured OMDbClient.
    """
    log = logging.getLogger(__name__)

    for raw in raw_movies:
        try:
            imdb_id = tmdb.get_movie_external_ids(raw.id)
            raw.imdb_id = imdb_id
            if imdb_id:
                rating, votes = omdb.fetch_ratings(imdb_id)
                raw.imdb_rating = rating
                raw.imdb_vote_count = votes
            else:
                log.info("No IMDB ID for movie TMDB ID %d (%s).", raw.id, raw.title)
        except FatalAPIError:
            raise
        except Exception as exc:
            log.warning("IMDB enrichment failed for movie '%s': %s", raw.title, exc)

    for raw in raw_series:
        try:
            imdb_id = tmdb.get_tv_external_ids(raw.id)
            raw.imdb_id = imdb_id
            if imdb_id:
                rating, votes = omdb.fetch_ratings(imdb_id)
                raw.imdb_rating = rating
                raw.imdb_vote_count = votes
            else:
                log.info("No IMDB ID for TV TMDB ID %d (%s).", raw.id, raw.title)
        except FatalAPIError:
            raise
        except Exception as exc:
            log.warning("IMDB enrichment failed for series '%s': %s", raw.title, exc)

    omdb.log_summary()


def _enrich_with_ott(
    raw_movies: List[RawMovie],
    raw_series: List[RawTVSeries],
    tmdb: TMDBClient,
) -> None:
    """
    Attach Indian OTT platform lists to each raw record in-place.

    Args:
        raw_movies:  List of RawMovie records to enrich.
        raw_series:  List of RawTVSeries records to enrich.
        tmdb:        Configured TMDBClient.
    """
    log = logging.getLogger(__name__)
    ott_found = 0

    for raw in raw_movies:
        try:
            platforms = tmdb.get_movie_watch_providers(raw.id)
            raw.ott_platforms = platforms
            if platforms:
                ott_found += 1
        except FatalAPIError:
            raise
        except Exception as exc:
            log.warning("OTT enrichment failed for movie '%s': %s", raw.title, exc)

    for raw in raw_series:
        try:
            platforms = tmdb.get_tv_watch_providers(raw.id)
            raw.ott_platforms = platforms
            if platforms:
                ott_found += 1
        except FatalAPIError:
            raise
        except Exception as exc:
            log.warning("OTT enrichment failed for series '%s': %s", raw.title, exc)

    log.info("OTT enrichment: %d titles with confirmed Indian OTT availability.", ott_found)


def _download_posters(
    raw_movies: List[RawMovie],
    raw_series: List[RawTVSeries],
    tmdb: TMDBClient,
) -> None:
    """
    Download poster images for all raw records in-place.

    Args:
        raw_movies:  RawMovie records to enrich.
        raw_series:  RawTVSeries records to enrich.
        tmdb:        Configured TMDBClient.
    """
    log = logging.getLogger(__name__)
    downloaded = 0
    placeholders = 0

    all_records = list(raw_movies) + list(raw_series)
    for raw in all_records:
        if raw.poster_path:
            try:
                image_bytes = tmdb.download_poster(raw.poster_path)
                if image_bytes:
                    raw.poster_image = image_bytes
                    downloaded += 1
                else:
                    log.warning(
                        "Poster download failed for TMDB ID %d (%s), using placeholder.",
                        raw.id, raw.title,
                    )
                    placeholders += 1
            except Exception as exc:
                log.warning(
                    "Poster download error for TMDB ID %d (%s): %s. Using placeholder.",
                    raw.id, raw.title, exc,
                )
                placeholders += 1
        else:
            placeholders += 1

    log.info("Posters: %d downloaded, %d using placeholder.", downloaded, placeholders)


# ---------------------------------------------------------------------------
# V2 enrichment helpers
# ---------------------------------------------------------------------------


def _enrich_with_trends(items: List[ContentItem], fetcher: GoogleTrendsFetcher) -> None:
    """
    Enrich items with Google Trends India interest score (UC-016).

    Mutates each ContentItem in-place by setting google_trends_score.
    None is stored when pytrends returns no data or raises an exception;
    the scoring formula treats None as 0.0 (NFR-009).

    Args:
        items:   Pre-selected candidate pool to enrich.
        fetcher: Configured GoogleTrendsFetcher instance.
    """
    log = logging.getLogger(__name__)
    for item in items:
        try:
            score = fetcher.get_interest(title=item.title, year=item.release_year)
            item.google_trends_score = score
        except Exception as exc:
            log.warning(
                "[TRENDS] Unexpected error enriching '%s': %s. Defaulting to 0.",
                item.title, exc,
            )
            item.google_trends_score = None


def _enrich_with_youtube(
    items: List[ContentItem],
    fetcher: Optional[YouTubeFetcher],
) -> None:
    """
    Enrich items with YouTube trailer view count (UC-017).

    Mutates each ContentItem in-place by setting youtube_views.
    No-op if fetcher is None (YOUTUBE_API_KEY not configured, FR-025).
    None is stored when no trailer is found or an error occurs;
    the scoring formula treats None as 0 (NFR-009).

    Args:
        items:   Pre-selected candidate pool to enrich.
        fetcher: Configured YouTubeFetcher instance, or None to skip.
    """
    if fetcher is None:
        return

    log = logging.getLogger(__name__)
    for item in items:
        try:
            views = fetcher.get_trailer_views(title=item.title, year=item.release_year)
            item.youtube_views = views
        except Exception as exc:
            log.warning(
                "[YOUTUBE] Unexpected error enriching '%s': %s. Defaulting to 0.",
                item.title, exc,
            )
            item.youtube_views = None


# ---------------------------------------------------------------------------
# Indian language discover supplement
# ---------------------------------------------------------------------------


def _fetch_discover_supplement(
    raw_movies: List[RawMovie],
    raw_series: List[RawTVSeries],
    tmdb: TMDBClient,
) -> Tuple[List[RawMovie], List[RawTVSeries]]:
    """
    Supplement trending results with language-specific TMDB discover calls.

    Global trending skews toward English/Hollywood content. This function
    adds Hindi, Kannada, Tamil, Telugu, and Malayalam content via targeted
    discover queries, ensuring Indian language films are always in the
    candidate pool regardless of global trending position.

    Uses 1 page per language×genre combo to conserve API quota (~40 calls).

    Args:
        raw_movies: Existing trending movie records (mutated by dedup).
        raw_series: Existing trending TV records (mutated by dedup).
        tmdb:       Configured TMDBClient.

    Returns:
        Tuple of (supplemented_movies, supplemented_series) with deduplication.
    """
    log = logging.getLogger(__name__)

    seen_movie_ids = {r.id for r in raw_movies}
    seen_series_ids = {r.id for r in raw_series}
    added_movies = 0
    added_series = 0

    for lang in DISCOVER_LANGUAGES:
        for genre_id in DISCOVER_MOVIE_GENRE_IDS:
            try:
                discovered = tmdb.discover_movies(genre_id=genre_id, language=lang, max_pages=1)
                for r in discovered:
                    if r.id not in seen_movie_ids:
                        raw_movies.append(r)
                        seen_movie_ids.add(r.id)
                        added_movies += 1
            except Exception as exc:
                log.warning("Discover movies failed (lang=%s, genre=%d): %s", lang, genre_id, exc)

        for genre_id in DISCOVER_TV_GENRE_IDS:
            try:
                discovered = tmdb.discover_tv(genre_id=genre_id, language=lang, max_pages=1)
                for r in discovered:
                    if r.id not in seen_series_ids:
                        raw_series.append(r)
                        seen_series_ids.add(r.id)
                        added_series += 1
            except Exception as exc:
                log.warning("Discover TV failed (lang=%s, genre=%d): %s", lang, genre_id, exc)

    log.info(
        "Discover supplement: added %d movies and %d series from Indian languages %s.",
        added_movies, added_series, DISCOVER_LANGUAGES,
    )
    return raw_movies, raw_series


# ---------------------------------------------------------------------------
# Language filter for raw records
# ---------------------------------------------------------------------------


def _filter_raw_by_language(
    raw_movies: List[RawMovie],
    raw_series: List[RawTVSeries],
) -> Tuple[List[RawMovie], List[RawTVSeries]]:
    """
    Filter raw records by language accessibility.

    A record passes if:
      1. original_language is in SUPPORTED_LANGUAGES (hi/en/kn/ta/te/ml), OR
      2. spoken_languages includes a dub language (hi/en/kn) — covers
         non-Indian content dubbed for Indian OTT audiences.

    Args:
        raw_movies:  Raw movie records.
        raw_series:  Raw TV series records.

    Returns:
        Tuple of (filtered_movies, filtered_series).
    """
    log = logging.getLogger(__name__)
    langs = set(SUPPORTED_LANGUAGES)
    dubs = set(DUB_LANGUAGES)

    def _passes(record) -> bool:
        if record.original_language in langs:
            return True
        return any(code in dubs for code in record.spoken_languages)

    movies_before = len(raw_movies)
    series_before = len(raw_series)

    filtered_movies = [r for r in raw_movies if _passes(r)]
    filtered_series = [r for r in raw_series if _passes(r)]

    log.info(
        "Language filter: movies %d -> %d, tv %d -> %d",
        movies_before, len(filtered_movies),
        series_before, len(filtered_series),
    )
    return filtered_movies, filtered_series


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run_pipeline(dry_run: bool = False, force: bool = False) -> int:
    """
    Execute the full recommendation pipeline.

    Args:
        dry_run: If True, skip email delivery (save PDF locally only).
        force:   If True, bypass the Saturday gate.

    Returns:
        Exit code: 0 for success, 1 for fatal failure.
    """
    today = date.today()
    setup_logging(today)
    log = logging.getLogger(__name__)
    log.info("=" * 60)
    log.info("Weekly Movie Recommender — run start at %s", datetime.now().isoformat())
    log.info("=" * 60)

    # ------------------------------------------------------------------
    # UC-001: Saturday gate
    # ------------------------------------------------------------------

    if today.weekday() != 5 and not force:
        log.warning(
            "Today is %s (%s), not Saturday. Exiting cleanly. "
            "Use --force to run on non-Saturday days.",
            today.isoformat(),
            today.strftime("%A"),
        )
        return 0

    if force and today.weekday() != 5:
        log.info("--force flag set: bypassing Saturday gate (today is %s).", today.strftime("%A"))

    # ------------------------------------------------------------------
    # Config validation
    # ------------------------------------------------------------------

    try:
        cfg = load_config()
        log.info("Configuration validated successfully.")
    except EnvironmentError as exc:
        log.error("[FATAL] %s", exc)
        return 1

    # ------------------------------------------------------------------
    # Idempotency check (NFR-007)
    # ------------------------------------------------------------------

    if _already_sent(today) and not dry_run:
        log.info(
            "Email already sent for %s (sentinel file found). "
            "Skipping duplicate send to satisfy NFR-007.",
            today.isoformat(),
        )
        return 0

    # ------------------------------------------------------------------
    # Initialise API clients
    # ------------------------------------------------------------------

    tmdb = TMDBClient(cfg.tmdb_api_key)
    omdb = OMDbClient(cfg.omdb_api_key)

    # ------------------------------------------------------------------
    # UC-002 / UC-003: Fetch trending content
    # ------------------------------------------------------------------

    try:
        log.info("Fetching trending movies from TMDB...")
        raw_movies = tmdb.fetch_trending_movies()
        log.info("Fetched %d raw movie records.", len(raw_movies))

        log.info("Fetching trending TV series from TMDB...")
        raw_series = tmdb.fetch_trending_tv()
        log.info("Fetched %d raw TV series records.", len(raw_series))
    except FatalAPIError as exc:
        log.error("[FATAL] %s", exc)
        return 1

    if not raw_movies and not raw_series:
        log.error("[FATAL] Zero records fetched from TMDB. Cannot generate report.")
        return 1

    # ------------------------------------------------------------------
    # Supplement trending with Indian language discover calls
    # Ensures Hindi, Kannada, Tamil, Telugu, Malayalam content is always
    # in the candidate pool regardless of global trending position.
    # ------------------------------------------------------------------
    log.info("Supplementing with Indian language discover (languages: %s)...", DISCOVER_LANGUAGES)
    raw_movies, raw_series = _fetch_discover_supplement(raw_movies, raw_series, tmdb)
    log.info(
        "Total pool after supplement: %d movies, %d series.",
        len(raw_movies), len(raw_series),
    )

    # ------------------------------------------------------------------
    # UC-004: Language filter (on raw records before IMDB enrichment)
    # ------------------------------------------------------------------

    raw_movies, raw_series = _filter_raw_by_language(raw_movies, raw_series)

    # ------------------------------------------------------------------
    # UC-009: IMDB enrichment via OMDb
    # ------------------------------------------------------------------

    log.info("Starting OMDb enrichment for %d movies and %d series...",
             len(raw_movies), len(raw_series))
    try:
        _enrich_with_imdb(raw_movies, raw_series, tmdb, omdb)
    except FatalAPIError as exc:
        log.error("[FATAL] %s", exc)
        return 1

    # ------------------------------------------------------------------
    # Build ContentItems (converts raw records with genre resolution)
    # ------------------------------------------------------------------

    movie_items: List[ContentItem] = build_content_items_from_movies(raw_movies)
    series_items: List[ContentItem] = build_content_items_from_tv(raw_series)
    log.info("Built %d movie ContentItems, %d TV ContentItems.", len(movie_items), len(series_items))

    # ------------------------------------------------------------------
    # UC-005 / UC-006: Genre and recency filters
    # (Language filter already applied on raw records above)
    # Recency filter at ContentItem level for accurate date logging
    # ------------------------------------------------------------------

    movie_items = filter_by_recency(movie_items)
    series_items = filter_by_recency(series_items)

    log.info(
        "After recency filter: %d movies, %d series.",
        len(movie_items), len(series_items),
    )

    # ------------------------------------------------------------------
    # Rescore with populated imdb fields (score was computed with 0s initially)
    # ------------------------------------------------------------------

    for item in movie_items:
        item.score = score_item(item)
    for item in series_items:
        item.score = score_item(item)

    # ------------------------------------------------------------------
    # UC-018: Pre-select candidate pool for V2 enrichment (FR-022)
    # Select top (TOP_N * PRE_SELECT_MULTIPLIER) candidates per genre per
    # category so enrichment calls are bounded while all genre slots have
    # candidates (HIGH-001 fix: bucket first, then pre-select per bucket).
    # ------------------------------------------------------------------

    # Bucket first (without dedup — just for candidate selection)
    movie_genre_buckets = bucket_by_genre(movie_items)
    series_genre_buckets = bucket_by_genre(series_items)

    # Select top candidates per genre per category and merge into a set
    candidate_set: Dict[int, ContentItem] = {}
    for genre_items in list(movie_genre_buckets.values()) + list(series_genre_buckets.values()):
        for item in pre_select_candidates(genre_items, top_n=TOP_N, multiplier=PRE_SELECT_MULTIPLIER):
            candidate_set[item.id] = item

    all_candidates = list(candidate_set.values())
    log.info("V2 enrichment pool: %d candidates across all genres.", len(all_candidates))

    # UC-016: Google Trends enrichment (CRITICAL-002: wrap in try/except ImportError)
    try:
        trends_fetcher = GoogleTrendsFetcher(sleep_seconds=TRENDS_SLEEP_SECONDS)
        _enrich_with_trends(all_candidates, trends_fetcher)
        trends_fetcher.log_summary()
    except ImportError:
        log.warning(
            "pytrends is not installed — Google Trends enrichment skipped. "
            "Run: pip install pytrends"
        )

    # UC-017: YouTube enrichment (optional — skip if no API key)
    yt_fetcher: Optional[YouTubeFetcher] = None
    if cfg.youtube_api_key:
        yt_fetcher = YouTubeFetcher(api_key=cfg.youtube_api_key)  # CRITICAL-001: cfg not config
        _enrich_with_youtube(all_candidates, yt_fetcher)
        yt_fetcher.log_summary()
    else:
        log.warning(
            "YOUTUBE_API_KEY not set — YouTube enrichment skipped. "
            "Set it in .env to enable trailer view signals."
        )

    # Rescore with all 5 signals populated
    for item in all_candidates:
        item.score = score_item(item)

    # Rebuild movie_items and series_items from enriched candidates + non-candidate items
    # so all items remain available for genre bucketing (HIGH-001 fix).
    enriched_map = {item.id: item for item in all_candidates}
    movie_items = [enriched_map.get(item.id, item) for item in movie_items]
    series_items = [enriched_map.get(item.id, item) for item in series_items]

    log.info(
        "After V2 enrichment: %d movie candidates, %d series candidates.",
        len(movie_items), len(series_items),
    )

    # ------------------------------------------------------------------
    # UC-008: Bucket by genre, deduplicate, rank, select top-N
    # ------------------------------------------------------------------

    movie_buckets = bucket_by_genre(movie_items)
    series_buckets = bucket_by_genre(series_items)

    movie_buckets = deduplicate_across_genres(movie_buckets)
    series_buckets = deduplicate_across_genres(series_buckets)

    final_movies: Dict[str, List[ContentItem]] = {}
    final_series: Dict[str, List[ContentItem]] = {}

    for genre in GENRE_ORDER:
        m_bucket = movie_buckets.get(genre, [])
        s_bucket = series_buckets.get(genre, [])

        selected_movies = rank_and_select(m_bucket, genre, TOP_N) if m_bucket else []
        selected_series = rank_and_select(s_bucket, genre, TOP_N) if s_bucket else []

        log.info(
            "Selected %d of %d for %s Movies.",
            len(selected_movies), len(m_bucket), genre,
        )
        log.info(
            "Selected %d of %d for %s Web Series.",
            len(selected_series), len(s_bucket), genre,
        )

        if selected_movies:
            final_movies[genre] = selected_movies
            log.info(
                "Top %s Movie: '%s' (score=%.4f)",
                genre, selected_movies[0].title, selected_movies[0].score,
            )
        if selected_series:
            final_series[genre] = selected_series
            log.info(
                "Top %s Series: '%s' (score=%.4f)",
                genre, selected_series[0].title, selected_series[0].score,
            )

    # ------------------------------------------------------------------
    # UC-014: Kannada content stats
    # ------------------------------------------------------------------

    all_selected = [
        item
        for bucket in (final_movies, final_series)
        for items in bucket.values()
        for item in items
    ]
    kn_count = sum(1 for item in all_selected if item.language == "kn")
    log.info("Kannada titles in final selection: %d", kn_count)

    # ------------------------------------------------------------------
    # UC-011: Download poster images (only for selected items)
    # ------------------------------------------------------------------

    # Collect only the selected raw records for poster download efficiency
    selected_ids_movies = {
        item.id for items in final_movies.values() for item in items
    }
    selected_ids_series = {
        item.id for items in final_series.values() for item in items
    }

    selected_raw_movies = [r for r in raw_movies if r.id in selected_ids_movies]
    selected_raw_series = [r for r in raw_series if r.id in selected_ids_series]

    log.info("Downloading poster images for %d selected titles...",
             len(selected_raw_movies) + len(selected_raw_series))
    _download_posters(selected_raw_movies, selected_raw_series, tmdb)

    # Propagate downloaded poster bytes back to ContentItems
    poster_map = {r.id: r.poster_image for r in selected_raw_movies + selected_raw_series}
    for genre_items in list(final_movies.values()) + list(final_series.values()):
        for item in genre_items:
            item.poster_image = poster_map.get(item.id)

    # ------------------------------------------------------------------
    # UC-010: OTT platform enrichment (only for the final selected items)
    # Runs after rank_and_select to avoid API calls for non-selected records.
    # ------------------------------------------------------------------

    log.info("Fetching Indian OTT watch providers for %d selected titles...",
             len(selected_raw_movies) + len(selected_raw_series))
    try:
        _enrich_with_ott(selected_raw_movies, selected_raw_series, tmdb)
    except FatalAPIError as exc:
        log.error("[FATAL] %s", exc)
        return 1

    # Propagate OTT platform data back to ContentItems
    ott_map = {r.id: r.ott_platforms for r in selected_raw_movies + selected_raw_series}
    for genre_items in list(final_movies.values()) + list(final_series.values()):
        for item in genre_items:
            if item.id in ott_map:
                item.ott_platforms = ott_map[item.id]

    # ------------------------------------------------------------------
    # UC-012: PDF generation
    # ------------------------------------------------------------------

    recommendations = {"movies": final_movies, "series": final_series}
    pdf_file = _pdf_path(today)

    log.info("Generating PDF report: %s", pdf_file)
    try:
        generate_pdf(recommendations, str(pdf_file), run_date=today)
        pdf_size_kb = pdf_file.stat().st_size // 1024
        log.info("PDF generated: %s | %d KB", pdf_file.name, pdf_size_kb)
    except Exception as exc:
        log.error("[FATAL] PDF generation failed: %s", exc, exc_info=True)
        return 1

    # ------------------------------------------------------------------
    # TMDB call count summary
    # ------------------------------------------------------------------

    log.info("[TMDB] Total API calls this run: %d", tmdb.call_count)
    if tmdb.call_count > 500:
        log.warning("[TMDB] Call count %d exceeded the 500/run budget (NFR-002).", tmdb.call_count)

    # ------------------------------------------------------------------
    # UC-013: Email delivery
    # ------------------------------------------------------------------

    if dry_run:
        log.info("--dry-run mode: skipping email. PDF saved to: %s", pdf_file)
    else:
        log.info("Sending email to %s...", cfg.recipient_email)
        try:
            send_report(
                pdf_path=str(pdf_file),
                gmail_address=cfg.gmail_address,
                gmail_app_password=cfg.gmail_app_password,
                recipient_email=cfg.recipient_email,
                week_date=today,
                recommendations=recommendations,
            )
            _mark_sent(today)
        except (FileNotFoundError, RuntimeError) as exc:
            log.error("[FATAL] Email delivery failed: %s", exc)
            return 1

    # ------------------------------------------------------------------
    # Log rotation (NFR-005)
    # ------------------------------------------------------------------

    rotate_logs()

    total_recs = sum(len(v) for v in final_movies.values()) + sum(len(v) for v in final_series.values())
    log.info(
        "Run complete. Total recommendations: %d. PDF: %s.",
        total_recs, pdf_file.name,
    )
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="weekly-movie-recommender",
        description=(
            "Generate and email a weekly movie & web series recommendation PDF. "
            "Runs automatically on Saturdays; use --force to test on other days."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run full pipeline and save PDF locally, but skip email delivery.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Bypass the Saturday gate and run on any day (for testing).",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    exit_code = run_pipeline(dry_run=args.dry_run, force=args.force)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
