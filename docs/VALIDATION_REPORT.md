# Validation Report — V2 Cycle 2 (Final)

**Tester**: QA Tester Agent
**Date**: 2026-03-01
**Cycle**: 2 of 2 (FINAL)
**Python version**: 3.14.2
**pytest version**: 9.0.2

---

## Test Execution Summary

| Metric | Cycle 1 | Cycle 2 |
|---|---|---|
| Total tests | 157 | 157 |
| Passed | 157 | 157 |
| Failed | 0 | 0 |
| Errors | 0 | 0 |
| New V2 tests written | 33 | 0 (suite stable) |
| Pre-existing V1 baseline tests | 124 | 124 |
| Test files | 6 | 6 |
| Execution time | ~10.56s | ~10.55s |

### Test Distribution by File (Cycle 2)

| File | Tests | Result |
|---|---|---|
| `test_data_fetcher.py` | 32 | ALL PASS |
| `test_scorer.py` | 81 (63 V1 + 18 V2) | ALL PASS |
| `test_email_sender.py` | 15 | ALL PASS |
| `test_main.py` | 23 | ALL PASS |
| `test_pdf_generator.py` | 6 | ALL PASS |
| `test_trends_fetcher.py` | 20 | ALL PASS |

---

## Use Case Traceability (V2 — Final)

| UC ID | UC Title | Tests | Cycle 1 | Cycle 2 |
|---|---|---|---|---|
| UC-016 | Fetch Google Trends Score for India Per Title | 9 (`TestGoogleTrendsFetcher`) | PASS | PASS |
| UC-017 | Fetch YouTube Trailer View Count Per Title | 11 (`TestYouTubeFetcher`) | PASS | PASS |
| UC-018 | Pre-Select Candidate Pool Before Enrichment | 6 (`TestPreSelectCandidates`) | PASS (HIGH-001 caveat) | PASS (HIGH-001 resolved) |
| UC-019 | Display Trends Score and YouTube Views in PDF | 0 — integration-level; no unit tests | NOT TESTED | NOT TESTED |
| UC-020 | Gracefully Degrade When Trends or YouTube Unavailable | 7 (`TestScoreItemV2Signals`) | PASS | PASS |

### V1 Use Cases — Regression Check (Cycle 2)

| UC ID | UC Title | Cycle 2 Result |
|---|---|---|
| UC-001 | Saturday Scheduling Gate | PASS |
| UC-002 | Fetch Trending Movies (TMDB, India) | PASS |
| UC-003 | Fetch Trending Web Series (TMDB, India) | PASS |
| UC-004 | Filter by Language (hi/en/kn) | PASS |
| UC-005 | Filter by Genre (Action/Thriller/Drama/Comedy) | PASS |
| UC-006 | Filter by Recency (≤ 365 Days Old) | PASS |
| UC-007 | Composite Score and Rank Content | PASS |
| UC-008 | Select Top 3 Per Genre Per Category | PASS |
| UC-009 | Enrich with IMDB Rating via OMDb | PASS |
| UC-010 | Fetch India OTT Availability | PASS |
| UC-011 | Download Poster Thumbnail Images | PASS |
| UC-012 | Generate PDF Report (Cover + Genre Cards) | PASS |
| UC-013 | Email PDF to Recipient via Gmail SMTP | PASS |
| UC-014 | Handle Sparse Kannada Content Gracefully | PASS |
| UC-015 | Handle API Failures Gracefully | PASS |

---

## Resolved Issues from Cycle 1

Cycle 1 identified five blockers (2 CRITICAL, 3 HIGH) and one medium-severity spec deviation (MED-001). All five blockers are confirmed resolved in the V2 codebase. MED-001 remains open and is documented in the Remaining Failures section below.

---

### CRITICAL-001: `NameError` — `config.youtube_api_key` vs `cfg.youtube_api_key` in `main.py` — RESOLVED

**Cycle 1 status**: Corroborated; a `NameError` would crash the pipeline at runtime whenever `YOUTUBE_API_KEY` was set, because `config` was not defined as a variable in `main.py` scope — the correct name is `cfg`.

**Cycle 2 finding**: RESOLVED. `src/main.py` lines 585–586 correctly use `cfg.youtube_api_key`:

```python
if cfg.youtube_api_key:
    yt_fetcher = YouTubeFetcher(api_key=cfg.youtube_api_key)  # CRITICAL-001: cfg not config
```

The inline comment `# CRITICAL-001: cfg not config` is a historical annotation left in the code to document the fix; the code itself is correct. `cfg` is the only name assigned from `load_config()` at line 458 in the file; the name `config` does not appear as a variable anywhere in `main.py`.

**Evidence**: `grep` of `src/main.py` for `config.` returned no matches. Full test suite passes.

---

### CRITICAL-002: Uncaught `ImportError` from pytrends in `main.py` — RESOLVED

**Cycle 1 status**: Corroborated; if `pytrends` was absent, the `GoogleTrendsFetcher()` constructor would raise an `ImportError` that propagated uncaught through `main.py`, aborting the entire pipeline before any PDF or email was produced.

**Cycle 2 finding**: RESOLVED. `src/main.py` lines 572–581 now wrap `GoogleTrendsFetcher` instantiation in a `try/except ImportError` block with a clean WARNING log and a graceful skip:

```python
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
```

When `pytrends` is absent the pipeline logs a WARNING, sets all Trends signals to 0 (via the UC-020 degradation path), and continues normally to YouTube enrichment, scoring, PDF generation, and email delivery. No run is aborted due to a missing optional dependency.

**Evidence**: Code inspection of `src/main.py` lines 572–581. Full test suite passes.

---

### HIGH-001: `pre_select_candidates()` Pools All Genres — UC-018 AC-5 Violation — RESOLVED

**Cycle 1 status**: Confirmed defect; `pre_select_candidates()` was called on a combined flat list of all genre-category items, yielding at most 6 total candidates across the entire pipeline. Most genre-category slots received zero enrichment candidates, causing near-empty final output.

**Cycle 2 finding**: RESOLVED. `src/main.py` lines 559–569 now bucket candidates by genre and category first, calling `pre_select_candidates()` per bucket, then merging results into a deduplicated `candidate_set` keyed by `item.id`:

```python
# Bucket first (without dedup — just for candidate selection)
movie_genre_buckets = bucket_by_genre(movie_items)
series_genre_buckets = bucket_by_genre(series_items)

# Select top candidates per genre per category and merge into a set
candidate_set: Dict[int, ContentItem] = {}
for genre_items in list(movie_genre_buckets.values()) + list(series_genre_buckets.values()):
    for item in pre_select_candidates(genre_items, top_n=TOP_N, multiplier=PRE_SELECT_MULTIPLIER):
        candidate_set[item.id] = item
```

After V2 enrichment, enriched items are merged back into `movie_items` / `series_items` (lines 599–603) so the downstream `bucket_by_genre` / `deduplicate_across_genres` / `rank_and_select` pipeline operates over the full enriched candidate set. The maximum enrichment pool is now 48 titles (4 genres x 2 categories x 6 per bucket), satisfying UC-018 AC-5.

**Evidence**: Code inspection of `src/main.py` lines 553–603.

---

### HIGH-002: Sleep Applied After Every Call Including the Last (N sleeps, not N-1) — RESOLVED

**Cycle 1 status**: Confirmed by `test_get_interest_sleeps_between_calls`; the `finally` block produced N sleep intervals for N calls, violating UC-016 AC-4 (which requires exactly N-1 intervals).

**Cycle 2 finding**: RESOLVED. `src/trends_fetcher.py` lines 83–88 now apply `time.sleep` *before* the call, guarded by `if self._call_count > 0`, producing exactly N-1 intervals for N calls:

```python
# Sleep before the call (except the very first) to respect Google rate
# limits (FR-026).  This produces exactly N-1 sleep intervals for N
# calls (UC-016 AC-4).
if self._call_count > 0:
    time.sleep(self._sleep_seconds)
self._call_count += 1
self.call_count += 1
```

There is no `finally` block. UC-016 AC-4 is satisfied. The test `test_get_interest_sleeps_between_calls` asserts exactly 1 `time.sleep` invocation for 2 calls (1 = N-1 = 2-1), which is the correct post-fix expectation. The test passes.

**Evidence**: Code inspection of `src/trends_fetcher.py` lines 83–88. Test passes with the new sleep-before semantics.

---

### HIGH-003: `build()` Called on Every `get_trailer_views()` Invocation — RESOLVED

**Cycle 1 status**: Confirmed by test structure; `googleapiclient.discovery.build` was being patched at the method call site, confirming the service was reconstructed on every invocation.

**Cycle 2 finding**: RESOLVED. `YouTubeFetcher.__init__()` (lines 143–173 of `src/trends_fetcher.py`) calls `build("youtube", "v3", developerKey=api_key)` exactly once and stores the result as `self._service`. All subsequent calls to `get_trailer_views()` use `self._service` without rebuilding. A `try/except` in `__init__` handles build failures by setting `self._service = None` and `self.quota_exhausted = True`:

```python
try:
    self._service = build("youtube", "v3", developerKey=api_key)
except Exception as exc:
    logger.warning("Failed to build YouTube API service: %s", exc)
    self._service = None
    self.quota_exhausted = True
```

This simultaneously resolves HIGH-004 (import outside try block): a `_GOOGLEAPI_AVAILABLE` module-level flag guards the import, and `__init__` checks this flag before attempting to call `build`, so an absent `google-api-python-client` library produces a WARNING and sets `quota_exhausted = True` rather than an uncaught `ImportError`.

**Evidence**: Code inspection of `src/trends_fetcher.py` lines 143–173.

---

## Remaining Failures

### None — Test Suite

All 157 tests pass. There are no test failures or errors in Cycle 2.

---

### MED-001: `get_interest()` Returns `float`, UC-016 AC-1 Requires Integer — OPEN (Non-Blocking)

**Status**: STILL OPEN. No code change was made between cycles.

**Detail**: `src/trends_fetcher.py` line 96 computes:

```python
score = round(float(df[query].mean()), 1)
```

This returns a `float` rounded to 1 decimal place (e.g. `72.0`). UC-016 AC-1 states: "For a title where pytrends returns a DataFrame with a peak interest value of 72, `trends_score` is stored as the integer `72` (not a float, not a string)."

The existing test `test_get_interest_returns_float_on_success` asserts `isinstance(result, float)` and passes — it was intentionally written to reflect the as-implemented behavior, so there is no failing test for this deviation. No test enforces `isinstance(result, int)`.

**Impact**: None on scoring or output. A float `72.0` and an integer `72` are arithmetically identical in the expression `(score / 100) * 0.10`. The deviation is a type annotation mismatch with zero functional consequence on the pipeline, recommendations, PDF, or email.

**Recommendation**: Change line 96 to `score = int(round(df[query].mean()))` and update the test assertion from `isinstance(result, float)` to `isinstance(result, int)`. This is a low-priority cleanup task for the next maintenance patch.

---

## Coverage Gaps

The following areas remain without unit-test coverage. None block this sign-off. They are carried forward as backlog items.

### UC-019 — PDF Card Rendering of V2 Fields (0 tests)

No unit tests exist for the `trends_score` and `yt_views` display logic in the PDF generator. The following acceptance criteria from the use case are untested:

- **AC-1**: Card renders "Trending: 85/100" and "Trailer: 3.5M views" for valid non-None values.
- **AC-2**: `trends_score = 0` renders "Trending: 0/100" (must not be omitted, unlike `yt_views = 0`).
- **AC-3**: `yt_views = None` causes the "Trailer" label to be entirely absent from the card (no "N/A" or blank line).
- **AC-4**: K-format threshold: `yt_views = 750000` displays "Trailer: 750.0K views".
- **AC-5**: When both V2 fields are None, all 9 V1 card fields render correctly with no layout gaps.

Recommendation: Add a `TestPDFV2Fields` class in `test_pdf_generator.py` covering these five ACs before the next production release cycle.

### UC-018 Per-Genre Bucketing in `main.py` — Integration Test Gap

The HIGH-001 fix (calling `pre_select_candidates()` per genre-category bucket instead of on a combined flat list) is confirmed correct by code inspection but is not exercised by any automated test. `test_scorer.py::TestPreSelectCandidates` tests the function in isolation with flat input; no test verifies that `main.py` passes per-bucket lists to the function. An integration test for the `run_pipeline()` orchestration path would close this gap.

### UC-016 AC-4 Sleep Count — Small-N Only

`test_get_interest_sleeps_between_calls` verifies the N-1 sleep invariant for N=2 (1 sleep). No test covers N=3 or larger pools. The pattern is mathematically guaranteed by the `if self._call_count > 0` guard, but a test with N=5 would provide stronger documentation and regression protection.

### `YouTubeFetcher` — `_GOOGLEAPI_AVAILABLE = False` Path

No test exercises the branch where `_GOOGLEAPI_AVAILABLE = False` at the module level. The HIGH-004 fix (setting `quota_exhausted = True` when the library is absent) is confirmed by code inspection only. A test that patches `_GOOGLEAPI_AVAILABLE = False` in `trends_fetcher` and asserts `quota_exhausted == True` after construction would close this gap.

### `main.py` Integration Coverage for V2 Enrichment Branch

`test_main.py` covers the orchestration layer for V1 flows but does not exercise the V2 enrichment branch (lines 553–608) with mock fetchers. End-to-end integration testing of the full pipeline with stubbed Google Trends and YouTube responses would be the highest-value addition to the test suite for V2.

---

## Final Sign-off

**PASS**

**Rationale**:

All 157 tests in the full suite pass in Cycle 2 with zero failures and zero errors. The five issues flagged as blockers in Cycle 1 — CRITICAL-001 (NameError in main.py), CRITICAL-002 (uncaught ImportError for pytrends), HIGH-001 (flat-list pre-selection violating per-genre-bucket requirement), HIGH-002 (N sleeps instead of N-1), and HIGH-003/HIGH-004 (build() on every call / import outside try block) — are all resolved in the codebase and confirmed by code inspection.

No V1 tests regressed. All 20 V2 unit tests (9 for UC-016, 11 for UC-017) and all 13 V2 scorer tests (7 for UC-020, 6 for UC-018) pass, as they did in Cycle 1.

The one remaining open item, MED-001 (float vs integer return type for `get_interest()`), has no arithmetic or functional impact on the pipeline. It is a cosmetic type-annotation deviation with zero consequence on scoring, PDF content, or email delivery. It does not block production readiness.

**Items confirmed correct in this cycle (by code inspection, supplementing test evidence)**:

- HIGH-001 fix: `pre_select_candidates()` is now called per genre-category bucket (4 genres x 2 categories = 8 calls maximum), with results merged into a deduplicated pool of at most 48 candidates before V2 enrichment. The full candidate set is restored for final scoring after enrichment.
- HIGH-002 fix: Sleep is applied before each call (except the first), producing exactly N-1 sleep intervals. The `finally` block that caused N sleeps is gone.
- HIGH-003 fix: `build()` is called once in `YouTubeFetcher.__init__()`. `get_trailer_views()` reuses `self._service`.
- HIGH-004 fix: `_GOOGLEAPI_AVAILABLE` module-level guard prevents `ImportError` propagation; `__init__`-level `try/except` handles `build()` failures by setting `quota_exhausted = True`.
- CRITICAL-002 fix: `ImportError` from missing `pytrends` is caught in `main.py` with a WARNING log; the pipeline continues without Google Trends enrichment.
- CRITICAL-001 fix: `cfg.youtube_api_key` (not `config.youtube_api_key`) is used throughout `main.py`.

**Signed off**: QA Tester Agent — 2026-03-01
