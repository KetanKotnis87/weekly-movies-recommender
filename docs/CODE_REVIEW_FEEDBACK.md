# Code Review Feedback — V2 Cycle 2 (FINAL)

**Reviewer**: Peer Code Reviewer Agent
**Date**: 2026-03-01
**Cycle**: 2 of 2 (FINAL)

---

## Executive Summary

All seven Cycle 1 CRITICAL and HIGH issues have been correctly resolved. The two runtime blockers
from Cycle 1 — the `NameError` crash on `config.youtube_api_key` (CRITICAL-001) and the uncaught
`ImportError` from pytrends (CRITICAL-002) — are both fixed. The architectural defect in
`pre_select_candidates()` (HIGH-001) is now properly addressed: `main.py` buckets by genre first,
runs per-bucket pre-selection, and merges enriched candidates back into the full item lists via an
`enriched_map` pattern, so all genre-category slots remain fully populated for the final ranking
pass. The YouTube API service object is built once in `__init__`, and the
`google-api-python-client` import guard is correctly implemented at module level using
`_GOOGLEAPI_AVAILABLE`. The N-1 sleep-interval fix in `GoogleTrendsFetcher` correctly adopts a
sleep-before strategy keyed on `_call_count > 0`, satisfying UC-016 AC-4 precisely.

The remaining unresolved items from Cycle 1 are all MEDIUM or LOW severity. Per the Cycle 2
policy, these are accepted as known issues and documented below; none are blockers for release.

Two new LOW-severity issues were identified in this cycle: (1) `GoogleTrendsFetcher.__init__`
maintains two parallel counters (`_call_count` and `call_count`) that are always incremented
together and are always equal, making `_call_count` redundant; (2) the outer `try/except Exception`
in `_enrich_with_trends()` (originally MED-004 in Cycle 1) remains in place and is still
technically unreachable given `get_interest()`'s own comprehensive internal exception handling.

---

## Verdict: APPROVED WITH CONDITIONS

The conditions are housekeeping items only (accepted known issues, all MEDIUM or LOW severity,
documented below). No further coding cycles are required. The pipeline is safe to deploy.

---

## Resolution Status of Cycle 1 Issues

| Issue ID | Severity | Status | Notes |
|---|---|---|---|
| CRITICAL-001 | CRITICAL | RESOLVED | `main.py:586` now correctly uses `cfg.youtube_api_key`. The undefined name `config` is gone. |
| CRITICAL-002 | CRITICAL | RESOLVED | `main.py:573-581` wraps `GoogleTrendsFetcher(...)` instantiation in `try/except ImportError`. A WARNING is logged and the pipeline continues with `trends_fetcher` never assigned (enrichment skipped). |
| HIGH-001 | HIGH | RESOLVED | `main.py:560-569` buckets `movie_items` and `series_items` by genre first using `bucket_by_genre()`, then calls `pre_select_candidates()` per genre bucket, merging results into a `candidate_set` dict keyed by `item.id`. After enrichment and rescoring, `main.py:601-603` rebuilds `movie_items`/`series_items` by merging `enriched_map` data back into the full lists, preserving all candidates for the final dedup/rank/select pass. Maximum enrichment pool is now up to 4 genres × 2 categories × 6 = 48 titles. |
| HIGH-002 | HIGH | RESOLVED | `trends_fetcher.py:86-88` sleeps **before** the call when `_call_count > 0`, producing exactly N-1 sleep intervals for N calls. UC-016 AC-4 satisfied. Sleep is not applied after the final call. |
| HIGH-003 | HIGH | RESOLVED | `YouTubeFetcher.__init__` builds the API service once at line 169 (`self._service = build(...)`). `get_trailer_views()` references `self._service` at line 194 via `service = self._service`, avoiding per-call reconstruction. If `build()` fails in `__init__`, `self._service = None` and `quota_exhausted = True` are set so all subsequent calls short-circuit gracefully. |
| HIGH-004 | HIGH | RESOLVED | Module-level `try/except ImportError` guard at `trends_fetcher.py:20-26` sets `_GOOGLEAPI_AVAILABLE = False` if `google-api-python-client` is not installed. `YouTubeFetcher.__init__` checks this flag at line 159 and disables itself cleanly. No per-call import attempted. |
| HIGH-005 | HIGH | RESOLVED | Dead `enriched_ids` variable removed. Replaced by the correct `enriched_map = {item.id: item for item in all_candidates}` merge pattern at `main.py:601-603`. |
| MED-001 | MEDIUM | UNRESOLVED | `ContentItem.google_trends_score` is still typed `Optional[float]` at `scorer.py:78`. `get_interest()` still returns `round(float(df[query].mean()), 1)` at `trends_fetcher.py:96` — a float, not an int. UC-016 AC-1 requires integer storage. Accepted as known issue. |
| MED-002 | MEDIUM | UNRESOLVED | `YOUTUBE_SEARCH_URL` and `YOUTUBE_VIDEOS_URL` still present as dead constants at `config.py:140-141`. Not imported or used anywhere. Accepted as known issue. |
| MED-003 | MEDIUM | UNRESOLVED | `pre_select_candidates()` docstring at `scorer.py:205-208` still inaccurately states "normalised to sum=0.80". The function uses the full 5-signal score with V2 fields at None=0, not a distinct partial formula. Accepted as known issue. |
| MED-004 | MEDIUM | UNRESOLVED | Outer `try/except Exception` in `_enrich_with_trends()` at `main.py:324-332` remains. `get_interest()` catches all exceptions internally and returns `None`; the outer handler is unreachable. Carried forward as NEW-LOW-002 in this cycle. Accepted. |
| MED-005 | MEDIUM | NOT VERIFIED | `.env.example` not provided in this review cycle; status from Cycle 1 unchanged. Accepted as known issue. |
| MED-006 | MEDIUM | UNRESOLVED | `_format_views()` in `pdf_generator.py:69-88` has no guard against negative input. Call-site guard (`item.youtube_views > 0` at line 384) prevents negative values from reaching the function in practice. Accepted as known issue. |
| LOW-001 | LOW | UNRESOLVED | `:.0f` format workaround at `pdf_generator.py:377` persists. Display output is correct. Linked to MED-001. Accepted. |
| LOW-002 | LOW | UNRESOLVED | Single `TrendReq` instance reused across all calls (`trends_fetcher.py:59`). Accepted (low practical risk; standard pytrends usage). |
| LOW-003 | LOW | UNRESOLVED | `YouTubeFetcher.log_summary()` at `trends_fetcher.py:264-268` logs only `call_count` and `quota_exhausted`. No `success_count` or `failed_count` tracking. Accepted as known issue. |
| LOW-004 | LOW | UNRESOLVED | UC-020 AC-4 combined scoring summary log line (`"Scoring: trends available for M of N titles; YouTube available for P of N titles"`) is not emitted anywhere in `main.py`. Accepted as known issue. |
| LOW-005 | LOW | UNRESOLVED | `TRENDS_GEO` and `TRENDS_TIMEFRAME` constants at `config.py:147-148` are defined but not used by `GoogleTrendsFetcher`. `build_payload()` at `trends_fetcher.py:92` hardcodes `geo="IN"` and `timeframe="now 7-d"` directly. Accepted as known issue. |
| LOW-006 | LOW | UNRESOLVED | `GoogleTrendsFetcher.__init__` does not validate `sleep_seconds >= 1.5`. A caller can pass `sleep_seconds=0.5` and violate FR-026 silently. Accepted as known issue. |

---

## New Issues Found in Cycle 2

### NEW-LOW-001: `GoogleTrendsFetcher` maintains two parallel, always-equal counters

- **File**: `src/trends_fetcher.py`, Lines 60-61, 88-89
- **Issue**: `__init__` initialises two separate integer counters:
  ```python
  self._call_count: int = 0   # internal counter used for sleep-before logic
  self.call_count: int = 0
  ```
  Both are unconditionally incremented on every call to `get_interest()`:
  ```python
  self._call_count += 1
  self.call_count += 1
  ```
  Since both start at 0 and are always incremented together with no branching between the two
  statements, they are guaranteed to be equal at all times. The only use of `_call_count` is the
  sleep-before guard at line 86: `if self._call_count > 0`. Since `call_count` starts at 0 and is
  incremented immediately after the guard check in the same method body, `call_count` could serve
  both the public telemetry role and the sleep-before gate: `if self.call_count > 0`. No separate
  `_call_count` field is necessary.
- **Risk**: No functional defect. Minor code smell that could mislead a future maintainer into
  believing the two counters may diverge under some code path.
- **Severity**: LOW
- **Fix** (deferred to V2.1): Remove `_call_count`. Change the sleep guard to
  `if self.call_count > 0`. Increment `self.call_count` once per call (the current second
  increment line becomes the only one).

---

### NEW-LOW-002: Outer `try/except` in `_enrich_with_trends()` is unreachable (MED-004 carry-over confirmed)

- **File**: `src/main.py`, Lines 324-332
- **Issue**: Confirmed unresolved from Cycle 1 MED-004. `GoogleTrendsFetcher.get_interest()`
  catches all exceptions internally via `except Exception` at `trends_fetcher.py:106` and
  returns `None` on any failure. The subsequent assignment `item.google_trends_score = score`
  on a dataclass attribute cannot raise. Therefore the `except Exception as exc` block at
  `main.py:327-332` is dead code that can never be triggered by normal or abnormal usage:
  ```python
  try:
      score = fetcher.get_interest(title=item.title, year=item.release_year)
      item.google_trends_score = score
  except Exception as exc:     # unreachable
      log.warning(...)
      item.google_trends_score = None
  ```
- **Risk**: No functional impact in the current code. Creates a false safety net: if
  `get_interest()` is ever refactored to re-raise exceptions, the outer handler would silently
  swallow them rather than propagating them.
- **Severity**: LOW (was classified MED-004 in Cycle 1; downgraded to LOW for this final cycle
  since it carries no runtime risk)
- **Fix** (deferred to V2.1): Remove the `try/except` wrapper in `_enrich_with_trends()`,
  leaving a simple `for item in items` loop with direct attribute assignments.

---

## Remaining Known Issues (accepted for this release)

The following items from Cycle 1 and the two new LOW issues from Cycle 2 are accepted as known
technical debt. None carry runtime blocker risk. All are deferred to V2.1.

### MED-001: `google_trends_score` stored as `float`; UC-016 AC-1 requires `int`

`get_interest()` in `trends_fetcher.py:96` returns `round(float(df[query].mean()), 1)` — a float.
`ContentItem.google_trends_score` is typed `Optional[float]` in `scorer.py:78`. The PDF renders
correctly using `:.0f` format (`pdf_generator.py:377`). Unit tests asserting an `int` type per
UC-016 AC-1 will fail until this is fixed. **Deferred to V2.1.**

### MED-002: Dead `YOUTUBE_SEARCH_URL` and `YOUTUBE_VIDEOS_URL` constants

`config.py:140-141`. Never imported or used. Mislead readers into thinking the fetcher uses
raw HTTP. **Deferred to V2.1 cleanup.**

### MED-003: Inaccurate `pre_select_candidates()` docstring

`scorer.py:205-208`. Claims a "normalised to sum=0.80" partial formula; the function simply
uses `item.score` with V2 fields defaulting to 0. **Deferred to V2.1.**

### MED-004 / NEW-LOW-002: Redundant outer `try/except` in `_enrich_with_trends()`

`main.py:324-332`. Unreachable dead exception handler. Detailed above as NEW-LOW-002.
**Deferred to V2.1.**

### MED-005: `.env.example` does not mark `YOUTUBE_API_KEY` as optional

Not reviewed in this cycle. Developer-experience gap; no runtime risk. **Deferred to V2.1.**

### MED-006: `_format_views()` not guarded against negative input

`pdf_generator.py:69-88`. Call-site guard (`youtube_views > 0` at line 384) prevents the
scenario in practice. **Deferred to V2.1.**

### LOW-001: `:.0f` display workaround for float trends score

`pdf_generator.py:377`. Cosmetically correct; resolved when MED-001 is fixed. **Deferred to V2.1.**

### LOW-002: Single `TrendReq` instance reused across all calls

`trends_fetcher.py:59`. Standard pytrends usage; very low risk. **Accepted; no action required.**

### LOW-003: `YouTubeFetcher.log_summary()` missing `success_count`/`failed_count`

`trends_fetcher.py:264-268`. Minor observability gap versus the symmetric `GoogleTrendsFetcher`
summary. **Deferred to V2.1.**

### LOW-004: UC-020 AC-4 combined scoring summary log line absent

No `"Scoring: trends available for M of N titles; YouTube available for P of N titles"` log line
emitted after V2 enrichment. AC-4 cannot be verified from logs alone. **Deferred to V2.1.**

### LOW-005: `TRENDS_GEO`/`TRENDS_TIMEFRAME` constants not used by `GoogleTrendsFetcher`

`config.py:147-148` vs `trends_fetcher.py:92`. Risk of configuration drift between documented
constants and actual behaviour. **Deferred to V2.1.**

### LOW-006: `sleep_seconds` not validated `>= 1.5` in `GoogleTrendsFetcher.__init__`

No `ValueError` raised on FR-026-violating values. **Deferred to V2.1.**

### NEW-LOW-001: Redundant dual counter in `GoogleTrendsFetcher`

`trends_fetcher.py:60-61`. No functional impact. Detailed above. **Deferred to V2.1.**

---

## PRD Alignment Check (Final)

| FR | Implemented? | Notes |
|---|---|---|
| FR-019 | Yes | `GoogleTrendsFetcher.get_interest()` queries `geo="IN"`, `timeframe="now 7-d"`. Failures return `None` (treated as 0 by scorer). `ImportError` guard in `main.py:573-581` ensures graceful skip when pytrends is absent. |
| FR-020 | Yes | `YouTubeFetcher.get_trailer_views()` uses `search.list` + `videos.list` two-step pattern. `maxResults=1`, `type="video"`. `_GOOGLEAPI_AVAILABLE` guard handles missing library. Failures return `None`. |
| FR-021 | Yes | 5-signal formula in `scorer.py:176-189`. Weights: 0.45 + 0.20 + 0.15 + 0.10 + 0.10 = 1.00. `None` V2 signals default to 0 via `or 0.0` / `or 0`. Maximum score = 1.0. |
| FR-022 | Yes | RESOLVED from Cycle 1. `main.py:560-569` buckets by genre first, pre-selects top-6 per genre-category bucket, merges into `candidate_set`. `enriched_map` at lines 601-603 merges back into full lists before final ranking. Maximum enrichment pool = 4 genres x 2 categories x 6 = 48 titles. |
| FR-023 | Partial | Quota math: 48 titles x (1 search + 1 videos) x 100 units = 9,600 units. Wait — re-checking: search.list = 100 units, videos.list = 1 unit; 48 x 101 = 4,848 units < 5,000 daily limit. Pool size is now correctly up to 48. No explicit "YouTube API units consumed" log line emitted; minor observability gap. |
| FR-024 | Yes | `pdf_generator.py:375-388`. `trends_para` rendered when `google_trends_score is not None` (includes score=0 per UC-019 AF-3). `youtube_para` rendered only when `youtube_views is not None and > 0` (omits 0-view titles per UC-019 AF-2). |
| FR-025 | Yes | `config.py:185` uses `os.environ.get("YOUTUBE_API_KEY", "").strip()` — no `EnvironmentError`. Absent key triggers WARNING at `main.py:590-593`; YouTube enrichment skipped entirely. |
| FR-026 | Yes | Sleep-before strategy at `trends_fetcher.py:86-88` produces exactly N-1 intervals for N calls, each >= 1.5 seconds. Sleep is not wasted after the final call. |

---

## Summary Counts

| Severity | Cycle 1 Count | Resolved in C2 | Remaining | New in C2 |
|---|---|---|---|---|
| CRITICAL | 2 | 2 | 0 | 0 |
| HIGH | 5 | 5 | 0 | 0 |
| MEDIUM | 6 | 0 | 6 | 0 |
| LOW | 6 | 0 | 6 | 2 |
| **Total** | **19** | **7** | **12** | **2** |

All 7 CRITICAL + HIGH issues from Cycle 1 are resolved. 12 MEDIUM/LOW issues remain and are
accepted as known issues for this release. 2 new LOW issues were identified in Cycle 2 (both
accepted and deferred to V2.1).

---

## Final Sign-off

**APPROVED WITH CONDITIONS**

All blocking defects (CRITICAL and HIGH) from Cycle 1 have been resolved. The V2 pipeline is
functionally correct: the 5-signal scoring formula is arithmetically sound (weights sum to 1.0),
the per-genre pre-selection pool is implemented correctly and conserves API quota, graceful
degradation paths for both pytrends and google-api-python-client are robust, and the NameError
crash that would have broken all YouTube-key deployments is eliminated.

The 12 remaining MEDIUM/LOW issues are accepted as known technical debt for V2. They carry no
runtime risk to the deployed pipeline and are deferred to a V2.1 housekeeping pass.

**Recommended V2.1 backlog items (in priority order)**:
1. Store `google_trends_score` as `int` (MED-001) — resolves LOW-001 display workaround as a side effect
2. Remove dead `YOUTUBE_SEARCH_URL` / `YOUTUBE_VIDEOS_URL` constants (MED-002)
3. Correct `pre_select_candidates()` docstring (MED-003)
4. Remove redundant `try/except` in `_enrich_with_trends()` (MED-004 / NEW-LOW-002)
5. Add optional comment to `.env.example` for `YOUTUBE_API_KEY` (MED-005)
6. Add `max(0, views)` guard to `_format_views()` (MED-006)
7. Add UC-020 AC-4 combined scoring summary log line (LOW-004)
8. Consume `TRENDS_GEO`/`TRENDS_TIMEFRAME` constants in `GoogleTrendsFetcher` (LOW-005)
9. Add `sleep_seconds >= 1.5` validation in `GoogleTrendsFetcher.__init__` (LOW-006)
10. Add `success_count`/`failed_count` to `YouTubeFetcher.log_summary()` (LOW-003)
11. Remove redundant `_call_count` counter (NEW-LOW-001)

**This code is cleared for production deployment.**
