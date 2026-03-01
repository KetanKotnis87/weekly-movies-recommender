# Code Review Feedback — V2 Cycle 1

**Reviewer**: Peer Code Reviewer Agent
**Date**: 2026-03-01
**Cycle**: 1 of 2

---

## Executive Summary

The V2 additions in `trends_fetcher.py` are well-structured with good docstrings, type hints, and
per-call error handling, and the 5-signal scoring formula in `scorer.py` is arithmetically correct
with weights summing to 1.0. However, there is one critical runtime crash (`NameError: config` on
line 568 of `main.py`), one critical graceful-degradation failure (uncaught `ImportError` when
`pytrends` is absent), and one high-severity logic defect in `pre_select_candidates()` that causes
it to pool all genres together rather than selecting top-6 per genre-category bucket as FR-022
requires. These three defects must be resolved before Cycle 2 sign-off.

## Verdict: REQUIRES REWORK

---

## Critical Issues (CRITICAL)

### CRITICAL-001: `NameError` crash — `config` is undefined; should be `cfg`

- **File**: `src/main.py`, Line 568
- **Issue**: The YouTube fetcher is conditionally constructed with:
  ```python
  if cfg.youtube_api_key:
      yt_fetcher = YouTubeFetcher(api_key=config.youtube_api_key)
  ```
  The variable holding the `Config` object is named `cfg` (assigned at line 458:
  `cfg = load_config()`). The name `config` is never defined anywhere in `main.py`.
  Every run where `YOUTUBE_API_KEY` is set will raise `NameError: name 'config' is not
  defined` at this line, crashing the pipeline before YouTube enrichment begins.
- **Risk**: YouTube enrichment is completely broken when an API key is provided. The pipeline
  exits with an unhandled exception (not a clean FATAL log + exit code 1), bypassing log
  rotation and the TMDB call-count summary.
- **Fix**: Change `config.youtube_api_key` to `cfg.youtube_api_key`:
  ```python
  yt_fetcher = YouTubeFetcher(api_key=cfg.youtube_api_key)
  ```

---

### CRITICAL-002: `ImportError` from `pytrends` is not caught — UC-016 AF-3 violated

- **File**: `src/main.py`, Line 561; `src/trends_fetcher.py`, Lines 48–51
- **Issue**: In `GoogleTrendsFetcher.__init__()`, the import of `pytrends.request.TrendReq`
  is deferred to the constructor body (line 48). If `pytrends` is not installed, this raises
  an `ImportError` at instantiation time. In `main.py` line 561, the instantiation:
  ```python
  trends_fetcher = GoogleTrendsFetcher(sleep_seconds=TRENDS_SLEEP_SECONDS)
  ```
  is not wrapped in any `try/except`. The `ImportError` propagates uncaught through
  `run_pipeline()` and terminates the process with a traceback rather than a clean exit.

  UC-016 AF-3 explicitly requires: "If the `pytrends` library is not installed or fails to
  import — the system logs a WARNING 'pytrends not available; Google Trends enrichment skipped
  for all titles', sets `trends_score = None` for every candidate, and proceeds directly to
  scoring." The current implementation does not satisfy this requirement.
- **Risk**: On a fresh PythonAnywhere deployment where `pip install pytrends` was skipped or
  failed silently, the entire pipeline aborts at the Trends step. No PDF is generated and no
  email is sent, violating NFR-009 (graceful V1 fallback).
- **Fix**: Wrap the `GoogleTrendsFetcher` instantiation in `main.py` in a `try/except
  (ImportError, Exception)` block. If it fails, log a WARNING, set `trends_fetcher = None`,
  and skip the `_enrich_with_trends` call. Alternatively, move the `pytrends` import to
  module level in `trends_fetcher.py` inside a `try/except ImportError` guard that sets a
  module-level flag `_PYTRENDS_AVAILABLE`, and check that flag before proceeding.

---

## High Severity Issues (HIGH)

### HIGH-001: `pre_select_candidates()` pools all genres together — violates FR-022 and UC-018

- **File**: `src/scorer.py`, Lines 197–231; `src/main.py`, Lines 556–558
- **Issue**: FR-022 specifies: "Google Trends and YouTube enrichment shall run only on a
  pre-selected candidate pool of **top-6 items per genre** (PRE_SELECT_MULTIPLIER=2 × TOP_N=3),
  not on all fetched items." UC-018 Main Flow step 1 says "the system groups the candidates
  by genre and category (Movies, Web Series)" and step 4 says "the system selects the top
  `min(6, N)` candidates **from each bucket**".

  However, `pre_select_candidates()` in `scorer.py` receives a single flat list and picks the
  globally top-6 items across all genres and both media types combined:
  ```python
  all_candidates = pre_select_candidates(
      movie_items + series_items, top_n=TOP_N, multiplier=PRE_SELECT_MULTIPLIER
  )
  ```
  With `top_n=3` and `multiplier=2`, `pool_size = 6`. This selects only 6 items in total
  across all genres and both media types — not 6 per genre per category. The maximum intended
  pool is 4 genres × 2 categories × 6 = 48 titles (UC-018 AC-5).

  In practice this means only 6 of potentially 50+ candidates receive Trends/YouTube
  enrichment. The other candidates are scored with 0 for both V2 signals, causing the final
  rankings to be no better than V1 for most titles. The 42 remaining candidates are then
  lost entirely at line 583–584 where `movie_items` and `series_items` are replaced with
  only the 6 enriched candidates:
  ```python
  movie_items = [item for item in all_candidates if item.media_type == "movie"]
  series_items = [item for item in all_candidates if item.media_type == "tv"]
  ```
  This means the final selection pool for genre bucketing is at most 6 items total, making
  it near-certain that most genre-category slots will have 0 recommendations.
- **Risk**: The pipeline produces a near-empty PDF (typically 0–6 cards across all 8 genre-
  category slots). This is a functional regression relative to V1 and violates FR-022, UC-018,
  and the 18-recommendation success metric.
- **Fix**: Refactor `pre_select_candidates()` to accept genre-bucketed items and select top-6
  per genre-category bucket. In `main.py`, bucket `movie_items` and `series_items` by genre
  first, run `pre_select_candidates()` per bucket, then pass the combined per-bucket pools
  to enrichment. After enrichment and rescoring, re-bucket and apply `rank_and_select()`.

---

### HIGH-002: `GoogleTrendsFetcher` sleeps after every call including the last — UC-016 AC-4

- **File**: `src/trends_fetcher.py`, Lines 99–101
- **Issue**: The `finally` block in `get_interest()` unconditionally calls
  `time.sleep(self._sleep_seconds)` after every request, including the final one:
  ```python
  finally:
      time.sleep(self._sleep_seconds)
  ```
  UC-016 AC-4 states: "When processing a pool of N titles, the total number of inter-request
  sleep intervals is exactly N - 1, and each interval is at least 1.5 seconds." With the
  current implementation, N calls produce N sleeps (not N-1), adding an unnecessary 1.5-second
  wait after the last title. For the maximum pool of 48 titles this wastes 1.5 seconds, and it
  means the actual runtime is `N × 1.5s` rather than `(N-1) × 1.5s`.
- **Risk**: Minor pipeline slowdown. AC-4 compliance failure if validated by integration test
  counting sleep intervals from log timestamps. NFR-008 budget (3 minutes for V2 enrichment)
  is not endangered by a single extra 1.5s, but the spec non-compliance is clear.
- **Fix**: Track call index in the caller (`_enrich_with_trends`) and skip the sleep after the
  last item, or restructure `get_interest()` to accept a `is_last_call: bool` parameter. The
  simplest fix in `main.py` is to apply the sleep in the enrichment loop explicitly between
  calls rather than inside the fetcher.

---

### HIGH-003: `YouTubeFetcher.get_trailer_views` rebuilds the API service object on every call

- **File**: `src/trends_fetcher.py`, Lines 158–164
- **Issue**: Inside `get_trailer_views()`, the `googleapiclient.discovery.build()` call:
  ```python
  service = build("youtube", "v3", developerKey=self._api_key)
  ```
  is placed inside the method body, so a new service object is constructed for every title.
  `googleapiclient.discovery.build()` performs an HTTP request to fetch the discovery
  document the first time it is called (it is cached subsequently), but constructing a new
  service object per call is unnecessary overhead and makes it harder to mock in tests.
- **Risk**: Minor performance overhead (discovery document fetch on first call). More
  importantly, the service object is constructed inside a `try` block that catches all
  `Exception` — if the build fails, the exception is logged and `None` returned, which
  silently swallows unexpected configuration errors.
- **Fix**: Construct the service object once in `__init__` and store it as `self._service`.
  Guard the construction with a `try/except` in `__init__` and set `self._service = None`
  on failure, then check `if self._service is None: return None` at the top of
  `get_trailer_views()`.

---

### HIGH-004: `google-api-python-client` import inside method on every call — UC-016 AF-3 analog

- **File**: `src/trends_fetcher.py`, Lines 158–159
- **Issue**: The imports:
  ```python
  from googleapiclient.discovery import build
  from googleapiclient.errors import HttpError
  ```
  are placed inside `get_trailer_views()` and executed on every invocation. If
  `google-api-python-client` is not installed, the `ImportError` propagates uncaught from
  inside the method, bypasses the outer `except Exception as exc` block (which is below the
  import, not around it — actually the imports ARE inside the `try` block starting at line
  163, so they ARE caught). Re-examining lines 163–175:
  ```python
  try:
      service = build("youtube", "v3", developerKey=self._api_key)
      ...
  except HttpError as exc:
      ...
  except Exception as exc:
      ...
  ```
  The imports at lines 158–159 are BEFORE the `try` block, meaning an `ImportError` from
  `from googleapiclient.discovery import build` is NOT caught and propagates to the caller.
  In `main.py`, `_enrich_with_youtube()` wraps each call in `try/except Exception`, so
  the `ImportError` would be caught there on the first call and logged as a warning — but
  subsequent calls would also attempt the import and fail again, logging a warning for every
  title in the pool (up to 48 warnings).
- **Risk**: Noisy log output if the library is absent. More importantly, unlike pytrends
  (which at least uses a deferred import to produce a descriptive error), there is no
  pre-flight check for `google-api-python-client` availability with a single skip-all
  WARNING per the spirit of UC-017 graceful degradation.
- **Fix**: Move the imports inside the `try` block (after line 163), or add a module-level
  `try/except ImportError` guard similar to what was intended for pytrends.

---

### HIGH-005: Enriched candidate IDs computed but `enriched_ids` variable is never used

- **File**: `src/main.py`, Line 582
- **Issue**: After V2 enrichment and rescoring, line 582 computes:
  ```python
  enriched_ids = {item.id for item in all_candidates}
  ```
  This variable is assigned but never referenced anywhere in the subsequent code. Lines
  583–584 replace `movie_items` and `series_items` directly without using `enriched_ids`.
  This is dead code.
- **Risk**: No functional impact in the current code. However, it suggests the original
  intent may have been to filter or merge enriched candidates back into the full item
  lists (rather than replacing them entirely), which is the correct V2 architecture that
  HIGH-001 identifies as missing.
- **Fix**: Remove the dead assignment, or (as part of the HIGH-001 fix) actually use
  `enriched_ids` to merge enriched data back into the full `movie_items`/`series_items`
  lists before genre bucketing.

---

## Medium Severity Issues (MED)

### MED-001: `score_item()` returns a `float`, but `google_trends_score` is also stored as `float` — UC-016 AC-1 type mismatch

- **File**: `src/trends_fetcher.py`, Line 80; `src/scorer.py`, Line 78
- **Issue**: UC-016 AC-1 states: "For a title where pytrends returns a DataFrame with a peak
  interest value of 72, `trends_score` is stored as the integer `72` (not a float, not a
  string)." The `ContentItem.google_trends_score` field is typed `Optional[float]` (scorer.py
  line 78), and `get_interest()` returns `round(float(df[query].mean()), 1)` — a `float`
  rounded to one decimal place (e.g., `72.0` or `71.4`). This violates the AC-1 integer
  requirement.
- **Risk**: Unit tests validating AC-1 will fail with a type assertion. The float value does
  not affect scoring (the formula divides by 100 regardless), but the spec non-compliance
  is clear.
- **Fix**: Change the return in `get_interest()` to `int(round(df[query].mean()))` and
  update `ContentItem.google_trends_score` to `Optional[int]` and the docstring accordingly.

---

### MED-002: `YOUTUBE_SEARCH_URL` and `YOUTUBE_VIDEOS_URL` constants in `config.py` are dead code

- **File**: `src/config.py`, Lines 140–141
- **Issue**:
  ```python
  YOUTUBE_SEARCH_URL: str = "https://www.googleapis.com/youtube/v3/search"
  YOUTUBE_VIDEOS_URL: str = "https://www.googleapis.com/youtube/v3/videos"
  ```
  These constants are defined but never imported or used anywhere. `YouTubeFetcher` uses
  `googleapiclient.discovery.build()` (which constructs its own URLs internally), not raw
  URL strings. These appear to be leftover from an earlier implementation approach.
- **Risk**: Dead code misleads readers into thinking the fetcher uses raw HTTP requests
  rather than the official client library.
- **Fix**: Remove both constants from `config.py`. If a raw-HTTP fallback is ever needed,
  add them back at that time.

---

### MED-003: `pre_select_candidates()` docstring claims weights "normalised to sum=0.80" — inaccurate

- **File**: `src/scorer.py`, Lines 205–208
- **Issue**: The docstring states:
  ```
  Partial score uses IMDB + popularity + votes only (V1 formula weights
  0.45/0.20/0.15, normalised to sum=0.80 so the ranking order is the same
  as the full formula with V2 signals at 0).
  ```
  The function does not use a partial formula at all — it uses `item.score` directly,
  which is computed by the full `score_item()` function with all 5 signals. Since V2 fields
  (`google_trends_score`, `youtube_views`) are `None` at this point in the pipeline, they
  contribute `0.0` to the score. The effective formula IS `0.45 + 0.20 + 0.15 = 0.80` of
  the maximum, but the docstring's claim about "normalised to sum=0.80" is mathematically
  misleading — the weights do not change; only the inputs are zero for V2 signals. A reader
  expecting a distinct partial-score formula will be confused.
- **Risk**: Misunderstanding of the pre-selection mechanism could lead to incorrect
  changes in future maintenance (e.g., someone adding a separate partial-scoring function
  unnecessarily).
- **Fix**: Rewrite the docstring to accurately state: "Items are sorted by their current
  composite score (computed by `score_item()`). Since V2 signals (`google_trends_score`,
  `youtube_views`) are `None` at this stage, they contribute 0 to the score, making the
  effective ranking equivalent to the 3-signal V1 formula."

---

### MED-004: `_enrich_with_trends()` has a redundant outer `try/except` — double wrapping

- **File**: `src/main.py`, Lines 323–332
- **Issue**: `_enrich_with_trends()` wraps `fetcher.get_interest()` in its own
  `try/except Exception`:
  ```python
  try:
      score = fetcher.get_interest(title=item.title, year=item.release_year)
      item.google_trends_score = score
  except Exception as exc:
      log.warning(...)
      item.google_trends_score = None
  ```
  However, `GoogleTrendsFetcher.get_interest()` already catches all exceptions internally
  (lines 90–97) and returns `None` on any failure. The outer `try/except` in
  `_enrich_with_trends()` can never be triggered by `get_interest()` — the only way it
  would fire is if `item.google_trends_score = score` itself raised an exception, which is
  not possible for a dataclass attribute assignment.
- **Risk**: Dead exception handler creates a false sense of security and adds noise. If
  `get_interest()` is ever refactored to re-raise exceptions, the outer handler would mask
  them silently.
- **Fix**: Remove the `try/except` wrapper in `_enrich_with_trends()`, relying on the
  already-robust error handling inside `get_interest()`. This simplifies the function to
  a straightforward iteration.

---

### MED-005: `.env.example` does not indicate `YOUTUBE_API_KEY` is optional

- **File**: `.env.example`, Line 15
- **Issue**: The file lists:
  ```
  YOUTUBE_API_KEY=your_youtube_api_key_here
  ```
  without any comment indicating that this variable is optional. The other four keys
  (`TMDB_API_KEY`, `OMDB_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`,
  `RECIPIENT_EMAIL`) are all required and will cause a startup `EnvironmentError` if
  absent. FR-025 specifies that `YOUTUBE_API_KEY` is optional and that the system should
  gracefully skip YouTube enrichment when it is absent. A developer setting up the service
  without a YouTube key may copy `.env.example` verbatim and be confused by the key format
  placeholder, or may not realise they can omit it entirely.
- **Risk**: Documentation gap that can cause unnecessary developer friction during setup.
- **Fix**: Add a comment above the `YOUTUBE_API_KEY` line:
  ```
  # YouTube Data API v3 key (optional — YouTube enrichment is skipped if absent)
  # Obtain from Google Cloud Console → Enable YouTube Data API v3
  YOUTUBE_API_KEY=your_youtube_api_key_here
  ```

---

### MED-006: `_format_views()` is not guarded against negative input

- **File**: `src/pdf_generator.py`, Lines 69–88
- **Issue**: `_format_views(views: int)` assumes a non-negative integer. No validation is
  performed. The docstring says "non-negative" but there is no assertion or guard. If
  `youtube_views` is somehow set to a negative integer (e.g., due to a data anomaly in a
  future YouTube API response change), `_format_views(-500_000)` would produce
  `-500.0K views`, which is nonsensical and would appear in the PDF.

  The call site in `_build_card()` (line 384) guards with `item.youtube_views > 0`, which
  would reject negative values correctly. However `_format_views` as a standalone utility
  function has no internal protection.
- **Risk**: Low in practice (the call site guard is correct), but the function is fragile
  as a reusable utility.
- **Fix**: Add `views = max(0, views)` at the top of `_format_views()`, or add an `assert
  views >= 0` if strict validation is preferred.

---

## Low Severity Issues (LOW)

### LOW-001: `google_trends_score` renders as integer in PDF but is stored as float

- **File**: `src/pdf_generator.py`, Line 377
- **Issue**: The trends score is rendered as:
  ```python
  f"Trending: {item.google_trends_score:.0f}/100"
  ```
  The `:.0f` format correctly suppresses the decimal point in the PDF output. However,
  the underlying stored value is a `float` (e.g., `71.4` if pytrends returns a non-integer
  mean). The display shows `71` which matches FR-024 ("Trending: N/100") and UC-019 AC-1.
  This is cosmetically correct but the `:.0f` is a workaround for storing a float when the
  spec requires an integer (see MED-001). Keeping this note for completeness.
- **Risk**: None in practice — display is correct.
- **Fix**: Addressed by MED-001 fix (store as `int`); then change format to `{item.google_trends_score}/100`.

---

### LOW-002: `TrendReq` instantiation re-uses single instance across all calls — no per-request session reset

- **File**: `src/trends_fetcher.py**, Lines 51
- **Issue**: `self._pytrends = TrendReq(hl="en-US", tz=330)` creates a single `TrendReq`
  instance reused across all `get_interest()` calls. Each call mutates the internal state
  of the `TrendReq` object via `build_payload()`. While this is the documented pytrends
  usage pattern, it means that if `build_payload()` fails partway through (before
  `interest_over_time()` is called), the object may be in an inconsistent state for the
  next call. The current exception handling catches this at the `interest_over_time()` call
  site and resets via the `finally` sleep, but a re-instantiation per call (or per N calls)
  would be more defensive.
- **Risk**: Very low — pytrends handles its own state correctly in normal usage.
- **Fix**: Consider re-instantiating `TrendReq` every N calls (e.g., every 10) as a
  defensive measure against session corruption.

---

### LOW-003: `YouTubeFetcher.log_summary()` does not report success/failure counts — asymmetric with `GoogleTrendsFetcher`

- **File**: `src/trends_fetcher.py`, Lines 234–238
- **Issue**: `GoogleTrendsFetcher.log_summary()` logs `call_count`, `success_count`, and
  `failed_count`. `YouTubeFetcher.log_summary()` logs only `call_count` and
  `quota_exhausted`. There is no `success_count` or `failed_count` tracking in
  `YouTubeFetcher`, making it harder to diagnose partial failures in the log.
- **Risk**: Minor observability gap.
- **Fix**: Add `self.success_count` and `self.failed_count` fields to `YouTubeFetcher`,
  increment them appropriately in `get_trailer_views()`, and include them in `log_summary()`.

---

### LOW-004: `UC-020 AC-4` scoring summary log line is not emitted

- **File**: `src/main.py` (no matching log call found)
- **Issue**: UC-020 AC-4 requires: "The execution log's scoring summary line matches the
  format 'Scoring: trends available for {M} of {N} titles; YouTube available for {P} of
  {N} titles'." No such summary line is logged anywhere in `main.py` after the V2
  enrichment and rescoring steps (lines 561–584). The individual fetchers log their own
  summaries (`trends_fetcher.log_summary()` at line 563, `yt_fetcher.log_summary()` at
  line 570), but neither produces the required combined format.
- **Risk**: UC-020 AC-4 acceptance criterion cannot be verified from logs.
- **Fix**: After the rescoring loop (after line 579), add:
  ```python
  trends_available = sum(1 for i in all_candidates if i.google_trends_score is not None)
  yt_available = sum(1 for i in all_candidates if i.youtube_views is not None)
  log.info(
      "Scoring: trends available for %d of %d titles; YouTube available for %d of %d titles.",
      trends_available, len(all_candidates), yt_available, len(all_candidates),
  )
  ```

---

### LOW-005: `TRENDS_GEO` and `TRENDS_TIMEFRAME` constants in `config.py` are not used by `GoogleTrendsFetcher`

- **File**: `src/config.py`, Lines 147–148; `src/trends_fetcher.py`, Line 76
- **Issue**:
  ```python
  TRENDS_GEO: str = "IN"
  TRENDS_TIMEFRAME: str = "now 7-d"
  ```
  These constants are defined in `config.py` but `GoogleTrendsFetcher.get_interest()`
  hardcodes `geo="IN"` and `timeframe="now 7-d"` directly in the `build_payload()` call
  (line 76), never importing or referencing these constants. If the geo or timeframe ever
  needs to change, there are two places to update (config.py constants and the hardcoded
  values in trends_fetcher.py), and they can drift out of sync.
- **Risk**: Configuration drift between documented constants and actual behaviour.
- **Fix**: Import `TRENDS_GEO` and `TRENDS_TIMEFRAME` from `src.config` in
  `trends_fetcher.py` and use them in the `build_payload()` call.

---

### LOW-006: `TRENDS_SLEEP_SECONDS` is imported in `main.py` but `sleep_seconds` is also a constructor default in `GoogleTrendsFetcher`

- **File**: `src/main.py`, Line 47; `src/trends_fetcher.py`, Line 40
- **Issue**: `TRENDS_SLEEP_SECONDS = 1.5` in `config.py` is imported and passed to the
  constructor in `main.py` (line 561: `GoogleTrendsFetcher(sleep_seconds=TRENDS_SLEEP_SECONDS)`).
  The constructor default is also `sleep_seconds: float = 1.5`. The constant is correctly
  used. However, the constructor docstring says "Must be >= 1.5 to comply with FR-026" but
  does not enforce this with a `ValueError` — a caller could pass `sleep_seconds=0.5` and
  violate FR-026 with no runtime error.
- **Risk**: FR-026 violation if the default is ever changed or overridden without awareness.
- **Fix**: Add validation in `__init__`:
  ```python
  if sleep_seconds < 1.5:
      raise ValueError(f"sleep_seconds must be >= 1.5 (FR-026); got {sleep_seconds}")
  ```

---

## Positive Observations

- **5-signal formula is arithmetically correct**: `score_item()` weights sum to exactly 1.0
  (0.45 + 0.20 + 0.15 + 0.10 + 0.10 = 1.00). All five components are correctly normalised
  to [0, 1] before weighting. The `None`-to-0 fallback for V2 signals is correctly
  implemented using `or 0.0` / `or 0` idioms. FR-021 is fully and correctly implemented.
- **`Config.youtube_api_key` is correctly optional**: `config.py` line 185 uses
  `os.environ.get("YOUTUBE_API_KEY", "").strip()` (no `_require()`), so absent or empty
  values do not raise `EnvironmentError`. FR-025 is correctly satisfied in the `Config`
  class.
- **HTTP 403 quota exhaustion handling in `YouTubeFetcher`**: The `quota_exhausted` flag
  pattern (lines 140, 155–156, 214–215) is correct — once set, all subsequent calls return
  `None` immediately without making further API calls, satisfying UC-017 AF-3.
- **`_format_views()` correctness**: The thresholds (>=1_000_000 for M, >=1_000 for K) are
  correct. `750_000` → "750.0K views" (UC-019 AC-4 ✓). `3_500_000` → "3.5M views"
  (UC-019 AC-1 ✓). `999` → "999 views" ✓. The `:.1f` precision matches the PRD spec.
- **Conditional rendering in `_build_card()` is correctly specified**: `trends_para` is
  rendered when `google_trends_score is not None` (includes 0, satisfying UC-019 AF-3 that
  score=0 should render "Trending: 0/100"). `youtube_para` requires both `is not None` and
  `> 0` (correctly omits 0-view titles per UC-019 AF-2).
- **`GoogleTrendsFetcher` error handling**: Per-call exception catching, always-sleep
  `finally` block, and `call_count` / `success_count` / `failed_count` telemetry are
  all well-implemented. The `TooManyRequestsError` is correctly caught by the broad
  `except Exception` since it is a subclass.
- **`requirements.txt` is PythonAnywhere-compatible**: Both `pytrends>=4.9.0` and
  `google-api-python-client>=2.100.0` are available via pip on PythonAnywhere free tier.
  No system-level C extensions are required. PythonAnywhere compatibility is maintained.
- **`YouTubeFetcher` search query**: The query format `"{title} {year} official trailer"`
  with `maxResults=1` and `type="video"` matches FR-020 exactly. The two-step
  search.list → videos.list pattern is the correct approach per the YouTube Data API v3
  best practices.
- **Docstrings and type hints**: Both `GoogleTrendsFetcher` and `YouTubeFetcher` have
  complete class and method docstrings with Args/Returns sections. All public methods have
  type hints. The module-level docstring correctly summarises both classes and their
  relationship to NFR-009.
- **`log_summary()` methods**: Both fetchers implement `log_summary()` which is correctly
  called in `main.py` after enrichment, providing per-run telemetry without requiring
  log parsing.

---

## PRD Alignment Check (V2)

| FR | Implemented? | Notes |
|---|---|---|
| FR-019 | Yes | `GoogleTrendsFetcher.get_interest()` queries geo=IN, timeframe="now 7-d". Failures default to 0. |
| FR-020 | Yes | `YouTubeFetcher.get_trailer_views()` uses search.list + videos.list pattern. Failures default to 0. |
| FR-021 | Yes | 5-signal formula correct; weights sum to 1.0; None values treated as 0. |
| FR-022 | No | `pre_select_candidates()` pools all genres together (top-6 total) instead of top-6 per genre per category (up to 48 total). See CRITICAL-001 and HIGH-001. |
| FR-023 | Partial | Quota math: 48 titles × (100 search + 1 videos) = 4,848 units < 5,000. But pool is actually only 6 titles (HIGH-001), so quota math is moot until fixed. No log line for "YouTube API units consumed". |
| FR-024 | Yes | "Trending: N/100" and "Trailer: X.XM views" rendered conditionally in `_build_card()`. Absent data is omitted correctly. |
| FR-025 | Yes | `YOUTUBE_API_KEY` loaded with `os.environ.get(...)` (no EnvironmentError). Missing key logs WARNING and skips enrichment. |
| FR-026 | Yes | `sleep_seconds=1.5` enforced via constructor default and `finally` block. Applies even on failure per FR-026. |

---

## Summary Counts

| Severity | Count |
|---|---|
| CRITICAL | 2 |
| HIGH | 5 |
| MEDIUM | 6 |
| LOW | 6 |
| **Total** | **19** |
