# Validation Report — Cycle 1

**Tester**: QA Tester Agent
**Date**: 2026-03-01
**Cycle**: 1 of 2

---

## Test Execution Summary

| Metric | Value |
|---|---|
| Total test cases | 122 |
| Passed | 107 |
| Failed | 15 |
| Errors | 0 |
| Test files | 5 |
| Python version | 3.14.2 |
| ReportLab version | 4.4.10 |

### Failure Distribution by Module

| Module | Passed | Failed |
|---|---|---|
| test_data_fetcher.py | 32 | 0 |
| test_scorer.py | 37 | 0 |
| test_email_sender.py | 15 | 0 |
| test_main.py | 23 | 0 |
| test_pdf_generator.py | 0 | 15 |

---

## Use Case Traceability Matrix

| UC ID | UC Title | Test(s) | Result |
|---|---|---|---|
| UC-001 | Saturday scheduling gate | `test_saturday_gate_allows_pipeline_to_proceed`, `test_monday_gate_exits_with_code_0_no_force`, `test_weekday_gate_exits_without_api_calls`, `test_non_saturday_various_weekdays_exit_cleanly`, `test_already_sent_returns_true_when_sentinel_exists`, `test_already_sent_returns_false_when_sentinel_missing`, `test_mark_sent_creates_sentinel_file`, `test_second_run_on_same_saturday_is_skipped_due_to_sentinel` | PASS |
| UC-002 | Fetch trending movies (TMDB, India) | `test_fetch_trending_movies_returns_parsed_list`, `test_fetch_trending_movies_empty_results`, `test_fetch_trending_movies_discards_records_missing_id`, `test_fetch_trending_movies_discards_records_missing_title` | PASS |
| UC-003 | Fetch trending web series (TMDB, India) | `test_fetch_trending_tv_returns_parsed_list`, `test_fetch_trending_tv_uses_name_field_not_title`, `test_fetch_trending_tv_discards_non_tv_media_type` | PASS |
| UC-004 | Filter by language (hi/en/kn) | `test_filter_keeps_hindi_english_kannada`, `test_filter_drops_tamil_content`, `test_filter_drops_telugu_content`, `test_filter_drops_malayalam_content`, `test_filter_empty_list_returns_empty`, `test_filter_custom_languages_parameter`, `test_filter_mixed_languages_returns_only_permitted` | PASS |
| UC-005 | Filter by genre (Action/Thriller/Drama/Comedy) | `test_bucket_by_genre_groups_items_correctly`, `test_bucket_by_genre_multi_genre_item_appears_in_multiple_buckets`, `test_bucket_by_genre_all_genre_keys_present`, `test_bucket_by_genre_empty_input_returns_empty_buckets` | PASS |
| UC-006 | Filter by recency (≤ 365 days old) | `test_filter_keeps_items_within_365_days`, `test_filter_drops_items_older_than_365_days`, `test_filter_keeps_item_exactly_365_days_old`, `test_filter_drops_item_366_days_old`, `test_filter_excludes_item_with_empty_release_date`, `test_filter_excludes_item_with_missing_release_date`, `test_filter_excludes_item_with_unparseable_date`, `test_filter_empty_list_returns_empty`, `test_filter_custom_days_parameter` | PASS |
| UC-007 | Composite score and rank content | `test_score_item_canonical_test_case`, `test_score_item_imdb_rating_zero_produces_valid_score`, `test_score_item_imdb_rating_none_does_not_raise`, `test_score_item_zero_votes_uses_log10_of_one`, `test_score_item_higher_popularity_yields_higher_score`, `test_score_rounded_to_4_decimal_places` | PASS |
| UC-008 | Select top 3 per genre per category | `test_rank_and_select_returns_top_3_sorted_by_score_desc`, `test_rank_and_select_returns_fewer_than_3_if_insufficient`, `test_rank_and_select_returns_two_when_two_available`, `test_rank_and_select_empty_input_returns_empty`, `test_rank_and_select_respects_top_n_parameter`, `test_rank_and_select_tiebreak_by_popularity` | PASS |
| UC-009 | Enrich with IMDB rating via OMDb | `test_fetch_ratings_parses_valid_response`, `test_fetch_ratings_na_returns_none_not_raises`, `test_fetch_ratings_na_votes_returns_zero`, `test_fetch_ratings_comma_votes_parsed_correctly`, `test_fetch_ratings_not_found_returns_none` | PASS |
| UC-010 | Fetch India OTT availability | `test_get_movie_watch_providers_returns_india_flatrate_names`, `test_get_movie_watch_providers_empty_when_no_india`, `test_get_tv_watch_providers_returns_india_flatrate_names`, `test_watch_providers_empty_when_api_fails`, `test_watch_providers_normalizes_prime_video_alias`, `test_watch_providers_excludes_non_permitted_platforms` | PASS |
| UC-011 | Download poster thumbnail images | `test_download_poster_returns_bytes_on_success`, `test_download_poster_returns_none_on_404`, `test_download_poster_returns_none_on_http_error`, `test_download_poster_returns_none_on_exception` | PASS |
| UC-012 | Generate PDF report (cover + genre cards) | `test_generate_produces_file_at_output_path`, `test_generated_file_is_valid_pdf`, `test_generated_pdf_size_under_10mb`, `test_generate_returns_output_path_string`, `test_generate_runs_without_error_when_poster_is_none`, `test_generate_embeds_valid_poster_image`, `test_generate_runs_without_error_when_genre_has_0_items`, `test_generate_runs_without_error_all_genres_empty`, `test_generate_all_4_genres_with_3_items_each`, `test_generate_with_single_item_genre`, `test_generate_uses_run_date_for_cover_page`, `test_generate_with_none_imdb_rating`, `test_generate_with_empty_overview`, `test_generate_with_both_movies_and_series` | **FAIL (all 15 tests)** |
| UC-013 | Email PDF to recipient via Gmail SMTP | `test_send_calls_smtp_with_correct_host_and_port`, `test_send_calls_starttls`, `test_send_calls_login_with_correct_credentials`, `test_send_attaches_pdf_with_correct_filename_format`, `test_send_raises_file_not_found_if_pdf_missing`, `test_send_raises_runtime_error_on_smtp_auth_failure`, `test_send_raises_runtime_error_on_smtp_connect_failure`, `test_send_raises_runtime_error_on_network_error`, `test_send_subject_contains_formatted_date`, `test_send_report_convenience_function_subject_format`, `test_send_report_subject_contains_em_dash`, `test_send_report_calls_smtp_correctly`, `test_send_report_raises_file_not_found_if_pdf_missing` | PASS |
| UC-014 | Handle sparse Kannada content gracefully | `test_rank_and_select_with_zero_kn_items_returns_best_available`, `test_filter_by_language_empty_kn_does_not_crash`, `test_all_genre_buckets_work_with_zero_kn_items`, `test_generate_runs_without_error_when_kn_items_are_zero` (FAIL — PDF bug), `test_generate_with_single_item_genre` (FAIL — PDF bug) | CONDITIONAL PASS* |
| UC-015 | Handle API failures gracefully | `test_retry_on_429_makes_multiple_calls`, `test_retry_on_503_makes_multiple_calls`, `test_fatal_on_401_raises_immediately_no_retries`, `test_fatal_api_error_is_raised_not_swallowed`, `test_all_retries_exhausted_returns_empty`, `test_returns_json_on_200`, `test_raises_fatal_on_401`, `test_returns_none_on_404`, `test_returns_none_on_400`, `test_retries_on_429_succeeds_on_second_attempt`, `test_fatal_api_error_causes_exit_code_1` | PASS |

*UC-014: Scorer-level and filter-level Kannada scarcity tests pass. PDF-level tests fail due to the PDF generator bug.

---

## Failed Test Details

All 15 failures share a single root cause in `src/pdf_generator.py`.

### Root Cause: `BaseDocTemplate.build()` does not accept `onFirstPage` / `onLaterPages` keyword arguments

**Affected tests (all 15 in `test_pdf_generator.py`)**:
- `TestPDFGeneratorOutput::test_generate_produces_file_at_output_path`
- `TestPDFGeneratorOutput::test_generated_file_is_valid_pdf`
- `TestPDFGeneratorOutput::test_generated_pdf_size_under_10mb`
- `TestPDFGeneratorOutput::test_generate_returns_output_path_string`
- `TestPDFPosterHandling::test_generate_runs_without_error_when_poster_is_none`
- `TestPDFPosterHandling::test_generate_embeds_valid_poster_image`
- `TestPDFGenreHandling::test_generate_runs_without_error_when_genre_has_0_items`
- `TestPDFGenreHandling::test_generate_runs_without_error_all_genres_empty`
- `TestPDFGenreHandling::test_generate_all_4_genres_with_3_items_each`
- `TestPDFGenreHandling::test_generate_with_single_item_genre`
- `TestKannadaScarcityNote::test_generate_runs_without_error_when_kn_items_are_zero`
- `TestKannadaScarcityNote::test_generate_uses_run_date_for_cover_page`
- `TestKannadaScarcityNote::test_generate_with_none_imdb_rating`
- `TestKannadaScarcityNote::test_generate_with_empty_overview`
- `TestKannadaScarcityNote::test_generate_with_both_movies_and_series`

**Error message** (identical for all 15):
```
TypeError: BaseDocTemplate.build() got an unexpected keyword argument 'onFirstPage'
```

**File and line**: `src/pdf_generator.py`, line 496:
```python
doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
```

**Root cause analysis**:
In ReportLab v4.x (installed: v4.4.10), `BaseDocTemplate.build()` signature is:
```python
def build(self, flowables, filename=None, canvasmaker=Canvas):
```
It does NOT accept `onFirstPage` or `onLaterPages` keyword arguments. These arguments are valid for `SimpleDocTemplate.build()` (a subclass), but `PDFReport._create_doc()` returns a `BaseDocTemplate` instance. The `_FooterCanvas` pattern in the source code was designed to use `PageTemplate` with frame-level callbacks, which is the correct approach for `BaseDocTemplate`, but the actual `doc.build()` call incorrectly uses the `SimpleDocTemplate`-style API.

**Link to code review issue**: CRITICAL-003 in `CODE_REVIEW_FEEDBACK_v1.md` identified `_FooterCanvas` as architecturally incorrect global-state mutable class pattern. This failure reveals the deeper problem: the API call itself is wrong for the document template type in use.

**Impact**: UC-012 (PDF generation) is completely non-functional. Since the pipeline generates the PDF before sending email, UC-013 email delivery would also fail in a full end-to-end run. This is a P0 blocker for the system.

**Required fix**: Change `doc.build(story, onFirstPage=on_page, onLaterPages=on_page)` to `doc.build(story)` and instead register the footer callback via the `PageTemplate.beforeDrawPage` or `PageTemplate.afterDrawPage` hook, or use a `canvas.Canvas` subclass. Alternatively, change `_create_doc()` to return a `SimpleDocTemplate`, though that would conflict with the multi-frame layout.

The simplest fix consistent with `BaseDocTemplate` usage:
```python
from reportlab.platypus import PageTemplate, Frame

report_date_str = run_date.strftime("%d %B %Y")

class FooterPageTemplate(PageTemplate):
    def __init__(self, date_str):
        self._date_str = date_str
        frame = Frame(left_margin, bottom_margin, ...)
        super().__init__(id="main", frames=[frame])

    def afterDrawPage(self, canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawCentredString(PAGE_WIDTH / 2, 18, f"Page {doc.page}  |  Generated on {self._date_str}  |  Weekly Watch List")
        canvas.restoreState()
```

---

## Additional Findings

### Finding: Two email subject tests required MIME decoding correction

Two tests in `test_email_sender.py` initially failed because the email subject containing the em-dash character (`—`, U+2014) is encoded by Python's `email.mime` as RFC 2047 encoded-word syntax (`=?utf-8?q?...?=`). The tests were updated to parse and decode the MIME message before asserting on the subject string. This is not a bug in the source code — it is correct MIME behavior — but required test-side awareness of encoding.

### Finding: Scoring formula matches FR-007 body text (CRITICAL-001 resolved in code)

The test `test_score_item_canonical_test_case` confirms that the actual formula weights are `0.4 / 0.4 / 0.2`:
- For `tmdb_popularity=100.0, imdb_rating=7.5, vote_count=10000`
- Score ≈ `40.0 + 30.0 + 0.8000 = 70.80`

This matches the FR-007 body text (not the review checklist alternative of `0.30 / 0.40 / 0.30`). The test passes, confirming the implementation is internally consistent with the UC-007 AC-1 acceptance criterion. CRITICAL-001 from the code review is a documentation ambiguity, not a code defect.

### Finding: Retry mechanism correctly retries on 429 and 503 (HIGH-001 partially observed)

Tests confirm the retry mechanism triggers on 429 and 503. However, as noted in HIGH-001, the 4-second final delay before giving up is never applied. The test `test_all_retries_exhausted_returns_empty` confirms 3 attempts are made but does not verify the 4s delay between attempt 2 and 3 (since `time.sleep` is mocked). This behavior is a known issue per HIGH-001 but does not cause test failures.

### Finding: OTT enrichment runs on all raw records (HIGH-004 documented)

The pipeline test `test_dry_run_generates_pdf_but_does_not_call_email_sender` confirms OTT enrichment (`get_movie_watch_providers`) is called on raw records before selection. No dedicated test for this API overuse was written (it would require counting exact TMDB call numbers in an integration context), but it is documented in HIGH-004 of the code review.

---

## Coverage Gaps

The following use cases or sub-scenarios were identified but lack full test coverage:

1. **UC-002 / UC-003: Multi-page pagination** — No test verifies that `fetch_trending_movies()` correctly fetches pages 2 and 3 when `total_pages > 1`. Only single-page responses are tested.

2. **UC-007: Tiebreak by alphabetical title** — The secondary-secondary tiebreak (alphabetical title when score AND popularity are identical) is not tested. The `test_rank_and_select_tiebreak_by_popularity` test covers the popularity tiebreak but not the title tiebreak.

3. **UC-009: OMDb rate-limit cutoff at 450 calls** — The `OMDB_RATE_LIMIT_WARN` threshold behavior (returns `None, 0` after 450 calls without making the API request) is not tested. A unit test calling `fetch_ratings()` 451 times would verify this.

4. **UC-010: Both Netflix and SonyLIV in single response** — UC-010 AC-3 requires `ott_platforms = ["Netflix", "SonyLIV"]` when both are present. The test `test_get_movie_watch_providers_returns_india_flatrate_names` verifies multiple platforms but does not assert the exact list ordering.

5. **UC-012: Cover page text content** — No test verifies the exact cover page text ("Saturday, DD Month YYYY" format per UC-012 AC-2) since PDF text extraction requires additional libraries not in requirements.

6. **UC-013: Email body content** — UC-013 AC-2 requires the body to list all genres and total count. No test verifies the email body content specifically (only subject and attachment filename are tested).

7. **UC-015: Exactly 4-second delay before third retry give-up** — HIGH-001 documents that the 4s delay in `RETRY_DELAYS[2]` is never applied. The existing tests mock `time.sleep` and verify call counts but do not verify the delay values passed to `time.sleep`.

8. **UC-015: OMDb 401 propagation through full pipeline** — No integration test verifies that an OMDb 401 (inside `_enrich_with_imdb`) propagates correctly through `run_pipeline()` to exit code 1.

9. **NFR-004: PDF size constraint with real poster images** — The `test_generated_pdf_size_under_10mb` test uses placeholder images (PDF generator bug prevents execution). With real poster images, the size constraint should be verified.

10. **NFR-005: Log rotation to 8 files** — No test verifies the `rotate_logs()` function deletes the oldest log file when 9 exist.

---

## Sign-off

**CONDITIONAL PASS**

**Rationale**: 107 of 122 tests (87.7%) pass. All failures are attributable to a single pre-existing bug in `src/pdf_generator.py` (line 496): `BaseDocTemplate.build()` does not accept `onFirstPage`/`onLaterPages` keyword arguments in the installed ReportLab v4.4.10. This bug renders UC-012 (PDF generation) completely non-functional, which in turn makes the full end-to-end pipeline unable to produce any output.

The system's data fetching (UC-002, UC-003), enrichment (UC-009, UC-010, UC-011), scoring (UC-004 through UC-008), email sending (UC-013), and orchestration (UC-001, UC-015) components are all functionally correct per test evidence. The Saturday gate, --force flag, --dry-run flag, and sentinel file idempotency all behave correctly.

**Required before Cycle 2 sign-off**:
1. Fix `src/pdf_generator.py` line 496: replace `doc.build(story, onFirstPage=on_page, onLaterPages=on_page)` with a correct `BaseDocTemplate`-compatible footer callback pattern.
2. After the fix, all 15 currently-failing PDF tests must pass.
3. Verify NFR-004 (10 MB size constraint) with the fixed PDF generator.

**Confidence level on passing components**: HIGH — data fetching, scoring, email delivery, and pipeline orchestration show correct behavior across 107 test cases covering happy paths, boundary conditions, error paths, and idempotency scenarios.
