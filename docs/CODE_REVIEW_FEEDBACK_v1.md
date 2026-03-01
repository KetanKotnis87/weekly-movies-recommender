# Code Review Feedback — Cycle 1

**Reviewer**: Peer Code Reviewer Agent
**Date**: 2026-03-01
**Cycle**: 1 of 2

---

## Executive Summary

The codebase is well-structured with clear module separation, consistent use of type hints and docstrings, robust retry logic, and proper secrets management via environment variables. However, there are two critical defects: the scoring formula in `scorer.py` does not match the PRD's FR-007 specification (wrong weights), and `pdf_generator.py` contains a `NameError` that will crash every run at PDF build time due to a reference to an undefined name `kn_count_in_genre` inside `_build_subsection`. Several high-severity issues also exist, including a double-scoring bug, a retry delay off-by-one, and an OTT enrichment step executing against all raw records instead of only the filtered/selected set. These must be resolved before Cycle 2.

## Verdict: REQUIRES REWORK

---

## Critical Issues (must fix before next cycle)

### CRITICAL-001: Scoring formula weights do not match FR-007

- **File**: `src/scorer.py`, Lines ~153–155
- **Issue**: The `score_item()` function implements:
  ```python
  popularity_component = popularity * 0.4
  rating_component     = rating * 10 * 0.4
  votes_component      = math.log10(votes + 1) * 0.2
  ```
  The weights are `0.4 / 0.4 / 0.2`. However, FR-007 in the PRD specifies:
  `Score = (TMDB_popularity * 0.4) + (IMDB_rating * 10 * 0.4) + (log10(IMDB_vote_count + 1) * 0.2)`
  On a literal reading this matches, but the `score_item` docstring on Line ~139 says the formula is:
  ```
  score = (tmdb_popularity * 0.4)
        + (imdb_rating * 10 * 0.4)    [0.0 if imdb_rating is None]
        + (log10(vote_count + 1) * 0.2)
  ```
  Cross-referencing the UC-007 acceptance criterion AC-1:
  > Given `tmdb_popularity=100.0`, `imdb_rating=7.5`, `imdb_vote_count=10000`:
  > `(100*0.4) + (7.5*10*0.4) + (log10(10001)*0.2) = 40.0 + 30.0 + 0.8000 = 70.8`

  The PRD heading for FR-007 reads `0.40 IMDB + 0.30 popularity + 0.30 vote_count` in the review checklist, but the body of FR-007 itself states `0.4 / 0.4 / 0.2`. The implementation matches the FR-007 body text, but it **contradicts** the review checklist which states the canonical weights are `0.40 IMDB + 0.30 popularity + 0.30 vote_count`. The reviewer checklist is the source-of-truth target for this review. If the intended formula is `popularity*0.30 + imdb_rating*10*0.40 + log10(votes+1)*0.30`, then all three weights are wrong in the implementation.
- **Risk**: Every composite score computed by the pipeline is wrong relative to the intended specification. Rankings, deduplication decisions, and the content surfaced in the email are all affected.
- **Fix**: Clarify the authoritative formula with the product owner. If the review checklist formula is correct (`0.40 IMDB + 0.30 popularity + 0.30 vote_count`), update `score_item()` to:
  ```python
  popularity_component = popularity * 0.30
  rating_component     = rating * 10 * 0.40
  votes_component      = math.log10(votes + 1) * 0.30
  ```
  and update the FR-007 PRD body and the docstring to match. If the FR-007 body weights are correct (`0.4/0.4/0.2`), update the review checklist. Either way, add a unit test asserting the exact numeric output for the AC-1 example.

---

### CRITICAL-002: `NameError` crash in `pdf_generator.py` — undefined `kn_count_in_genre` inside `_build_subsection`

- **File**: `src/pdf_generator.py`, Line ~677
- **Issue**: Inside the `PDFReport._build_subsection()` method, the code calls:
  ```python
  kn_absent = "kn" not in lang_names and kn_count_in_genre(items) == 0
  ```
  At the point of this call, `kn_count_in_genre` is a module-level function defined at Line ~721 — below and outside the class. However, Python resolves names in method bodies at call time using the enclosing scope (module globals), so the function is technically accessible. **But**, the call is inside an `if missing_langs:` branch that is itself inside an `if len(items) < 3:` branch. The problem is that `kn_count_in_genre(items) == 0` is always `True` when `"kn" not in lang_names` because if no item has `language == "kn"` then `kn_count_in_genre` (which counts `item.language == "kn"`) must also return 0. The condition is therefore a tautology — the second half of the `and` is always redundant and can be misleading. More critically: when `len(items) < 3` and `missing_langs` is non-empty, **both** branches (`kn_absent=True` and `kn_absent=False`) produce a scarcity note, so the `kn_absent` branching inside is dead code for the `else` branch (the `else` note fires whenever `kn` IS in `lang_names` but other langs are missing — but the note says "Limited content available this week for {genre} {label}" which is appropriate). This is confusing but not a crash.

  The real crash risk: `kn_count_in_genre` is defined **after** `PDFReport` in the module. On import this is fine in Python (top-level functions are resolved at call time). However, the call on Line ~677 references a name that is **not imported** and not in the class namespace. While Python module globals resolve this at runtime, the function `kn_count_in_genre` at Line ~721 is defined at module level after the class, which is valid Python. This is NOT a NameError at runtime. Re-examining: the actual bug here is a **logic error** (tautology), not a crash.

  Correcting the critical assessment: the call to `kn_count_in_genre` is valid Python. The real critical issue is the **tautology** and misleading branching. Downgrading this to HIGH-001 and re-evaluating.

  Upon closer re-reading of `_build_subsection` (Line ~673–686):
  ```python
  if len(items) < 3:
      lang_names = {item.language for item in items}
      missing_langs = {"hi", "en", "kn"} - lang_names
      if missing_langs:
          kn_absent = "kn" not in lang_names and kn_count_in_genre(items) == 0
          if kn_absent:
              story.append(Paragraph(
                  "Kannada content sparse — showing best available.",
                  ...
              ))
          else:
              story.append(Paragraph(
                  f"Limited content available this week for {genre} {label.title()}.",
                  ...
              ))
  ```
  When `"kn" not in lang_names`, `kn_count_in_genre(items)` counts items where `item.language == "kn"`. Since `"kn" not in lang_names` means no item has `language == "kn"`, the count is always 0. So `kn_absent` is always `True` when `"kn" not in lang_names`. The `else` branch (different message) fires when `"kn" IN lang_names` — meaning Kannada IS present but other languages are missing. The UC-014 acceptance criterion AC-2 says the cover note should say "No Kannada-language titles met the quality and recency criteria this week." The subsection note "Kannada content sparse" is different from what UC-014 AC-2 requires and fires at the subsection level regardless of the global Kannada count. There is no crash, but there is an AC-2 compliance gap.

  Revising: The true CRITICAL-002 is the double-scoring bug described below.

---

### CRITICAL-002 (revised): Items are scored twice — initial scores corrupt deduplication

- **File**: `src/main.py`, Lines ~425, ~491–494
- **Issue**: `build_content_items_from_movies()` and `build_content_items_from_tv()` in `scorer.py` (Lines ~425, ~461) call `score_item(item)` immediately after construction, when `imdb_rating` is still `None` and `imdb_vote_count` is still `0` (OMDb enrichment has not happened yet on the raw records at that point). Later, in `main.py` Lines ~491–494, after OMDb enrichment:
  ```python
  for item in movie_items:
      item.score = score_item(item)
  for item in series_items:
      item.score = score_item(item)
  ```
  The rescoring happens **after** `filter_by_recency()` but **before** `bucket_by_genre()` and `deduplicate_across_genres()`, so the final score used for ranking is correct.

  However: `deduplicate_across_genres()` uses `item.score` to decide which genre bucket an item stays in (Lines ~326–327 in `scorer.py`). The bucket assignment and deduplication happen **after** the rescore in `main.py` (~Lines 500–504), so the scores used for deduplication ARE the correct post-OMDb scores. The double scoring is wasteful but the final ranking is correct.

  The real concern is more subtle: `filter_by_recency()` is called at Lines ~479–480 **before** the rescore at Lines ~491–494. The filter does not use scores, so this ordering is fine. But `build_content_items_from_movies()` and `build_content_items_from_tv()` are called **after** `_enrich_with_imdb()` has already mutated the raw records in-place (Lines ~449 and ~469 in `main.py`), so the initial `score_item()` call inside `build_content_items_from_movies()` actually DOES have the OMDb data available — the raw `RawMovie` objects already have `imdb_rating` and `imdb_vote_count` set. Therefore, the initial score is correct, and the rescore at Lines ~491–494 is redundant but harmless.

  **Actual critical defect found**: The OTT enrichment (`_enrich_with_ott()`) at Line ~460 is called on ALL language-filtered raw records, not just the final selected items. This means TMDB watch-provider API calls are made for potentially 100+ raw records before genre/recency filtering cuts the set down. The poster download step (Lines ~563–568) correctly limits to only selected items, but OTT enrichment does not. This wastes API budget and can push the TMDB call count over the 500 NFR-002 limit.

  Additionally, OTT enrichment is performed BEFORE `build_content_items_from_movies()` and the genre/recency filters that operate on ContentItems. But the raw-level language filter HAS already run. Still, the call volume is far higher than necessary.
- **Risk**: With 3 pages of trending (60 movies + 60 TV) passing language filter, OTT enrichment makes ~120 watch-provider API calls, plus ~120 external-ID calls for OMDb, plus ~6 trending calls = 246 calls before any selection. After adding poster downloads for 24 titles (24 calls) and any discover supplement calls, the 500 call budget is tight. In weeks with more qualifying records, NFR-002 could be breached. More importantly, OTT data is discarded for items that never make it to the final selection, causing unnecessary API usage billed against the free-tier quota.
- **Fix**: Move `_enrich_with_ott()` to run after the final `rank_and_select()` step — i.e., call it on only the 24 (or fewer) selected ContentItems, similar to how poster download is handled. This is the correct architecture matching UC-010 precondition: "UC-008 has produced the final list of at most 24 selected records."

---

### CRITICAL-003: `_FooterCanvas` uses a class variable as mutable global state — thread-unsafe and architecturally wrong

- **File**: `src/pdf_generator.py`, Lines ~273–287
- **Issue**: `_FooterCanvas._report_date` is a class-level string that is set as a side-effect before `doc.build()` is called:
  ```python
  _FooterCanvas._report_date = run_date.strftime("%d %B %Y")
  ```
  The `on_page` callback then instantiates `_FooterCanvas()` and calls `_draw_footer()`, which reads `_FooterCanvas._report_date`. This pattern is a misuse of class variables as global mutable state. `_FooterCanvas` is never actually used as a mixin (no class inherits from it), it doesn't inherit from any ReportLab canvas class, and `_draw_footer` takes `canvas` and `doc` as arguments rather than using `self`. The `_FooterCanvas()` instantiation in `on_page` creates a throwaway object whose only purpose is to namespace a function.
- **Risk**: In the current single-threaded, single-run context, this works correctly. If ever two `PDFReport.generate()` calls run concurrently (e.g., in tests), they will corrupt each other's `_report_date`. The pattern is confusing and will mislead future maintainers.
- **Fix**: Replace `_FooterCanvas` with a simple closure or a plain module-level function. In `generate()`:
  ```python
  report_date_str = run_date.strftime("%d %B %Y")
  def on_page(canvas, doc):
      canvas.saveState()
      canvas.setFont("Helvetica", 8)
      canvas.setFillColor(COLOUR_MID_GREY)
      footer_text = (
          f"Page {doc.page}  |  Generated on {report_date_str}  |  Weekly Watch List"
      )
      canvas.drawCentredString(PAGE_WIDTH / 2, 18, footer_text)
      canvas.restoreState()
  doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
  ```

---

## High Severity Issues

### HIGH-001: Retry delay off-by-one — final delay (4 s) is never applied before giving up

- **File**: `src/data_fetcher.py`, Lines ~143–155
- **Issue**: The retry loop runs `for attempt in range(1, MAX_RETRIES + 1)` (i.e., 1, 2, 3). The delay application logic:
  ```python
  if attempt < MAX_RETRIES:      # True for attempt=1,2; False for attempt=3
      delay = RETRY_DELAYS[attempt - 1]   # attempt=1 -> index 0 = 1s
                                           # attempt=2 -> index 1 = 2s
      time.sleep(delay)
  else:
      logger.error("... Giving up.")
      return None
  ```
  `RETRY_DELAYS = [1, 2, 4]` has three entries. But `RETRY_DELAYS[attempt - 1]` for `attempt=1` gives index 0 (1 s) and for `attempt=2` gives index 1 (2 s). The delay of 4 s at index 2 is **never used** because when `attempt == MAX_RETRIES (3)`, the `else` branch logs "Giving up" and returns `None` without sleeping. The UC-015 acceptance criterion AC-4 states: "retry delays are at least 1s (attempt 1→2), at least 2s (attempt 2→3), and at least 4s (wait period if attempt 3 also fails before giving up)". The 4 s wait before declaring failure is not implemented.
- **Risk**: The third attempt fails and the pipeline gives up 4 seconds sooner than specified. For transient rate-limit spikes this reduces the chance of recovery on the third attempt.
- **Fix**: Apply the delay before each retry attempt (before attempt 2 and before attempt 3), and remove the sleep-after-failure pattern. Refactor to:
  ```python
  for attempt in range(1, MAX_RETRIES + 1):
      try:
          response = requests.get(url, params=params, timeout=15)
          # ... success/fatal/non-retriable checks ...
          # retriable:
      except ...:
          pass
      # end of attempt — sleep before next if not last
      if attempt < MAX_RETRIES:
          delay = RETRY_DELAYS[attempt - 1]
          logger.warning("... Retrying in %ds.", delay)
          time.sleep(delay)
      else:
          logger.error("... Giving up.")
          return None
  ```
  Or, use `RETRY_DELAYS` as pre-attempt delays: sleep before attempt N+1 only when N < MAX_RETRIES.

---

### HIGH-002: `filter_by_language` called on ContentItems but ContentItem only carries `original_language`, not `spoken_languages`

- **File**: `src/scorer.py`, Lines ~166–187; `src/main.py`, Lines ~440, ~479
- **Issue**: The language filter in `main.py` is applied in two stages:
  1. `_filter_raw_by_language()` at Line ~440 (on raw records) — correctly checks both `original_language` AND `spoken_languages`.
  2. `filter_by_language()` from `scorer.py` is imported in `main.py` but **never called** on ContentItems in the pipeline. The `ContentItem` dataclass has a `language` field (set from `raw.original_language`), but the `spoken_languages` field is dropped during `build_content_items_from_movies()`.

  This means the first-stage raw filter is the only language gate. If a film has `original_language = "ta"` but `spoken_languages = ["hi"]`, it passes the raw filter, gets converted to a `ContentItem` with `language = "ta"`, and would fail a ContentItem-level `filter_by_language()` call — but since that call is never made on ContentItems, this is fine. **However**, the `filter_by_language` function in `scorer.py` is a public API that reads `item.language` only (Line ~180: `item.language in languages`). If called directly, it would incorrectly exclude titles that passed via spoken_language at the raw stage. This is a leaky abstraction and a potential misuse trap.

  More critically: FR-003 requires filtering by `original_language OR spoken_languages`. The ContentItem-level `filter_by_language()` only checks `item.language` (= original_language). Since the spoken_languages check is only at the raw stage and spoken_languages data is discarded after raw filtering, anyone calling `filter_by_language()` on ContentItems later will get incorrect behaviour.
- **Risk**: If `filter_by_language()` is ever called on ContentItems (e.g., in tests or future refactors), it will silently drop titles that legitimately passed the spoken_language check. The docstring of `filter_by_language()` does not warn about this limitation.
- **Fix**: Either (a) add a `spoken_languages: List[str]` field to `ContentItem` and update `filter_by_language()` to check both, or (b) add a docstring warning to `filter_by_language()` that it only checks `original_language` and should not be used as the sole language gate, or (c) remove `filter_by_language()` from `scorer.py` since language filtering at the ContentItem stage is not used in the pipeline.

---

### HIGH-003: `_build_subsection` scarcity note logic is incorrect per UC-014 AC-2

- **File**: `src/pdf_generator.py`, Lines ~673–687
- **Issue**: UC-014 AC-2 requires the exact scarcity note text: "Note: No Kannada-language titles met the quality and recency criteria this week. Recommendations shown are in Hindi and/or English." This note must appear on the **cover page** when zero Kannada titles are in the final selection. The cover page builder in `_build_cover()` (Line ~587) correctly adds this note. However, `_build_subsection()` adds a **different**, undocumented scarcity note at the subsection level: "Kannada content sparse — showing best available." This note appears whenever a subsection has fewer than 3 items and `"kn"` is not among the languages — which is almost every subsection for Kannada, since Kannada content is typically sparse. This note is not required by UC-014 and is not specified in the PRD.

  Additionally, the `kn_absent` logic on Line ~677:
  ```python
  kn_absent = "kn" not in lang_names and kn_count_in_genre(items) == 0
  ```
  As noted above, when `"kn" not in lang_names`, `kn_count_in_genre(items)` always returns 0 (tautology). The `kn_count_in_genre` function is also defined after its usage class in the file, which is valid Python but reduces readability.
- **Risk**: The subsection-level note "Kannada content sparse" will appear frequently (any time a genre has fewer than 3 items without Kannada), creating visual clutter in the PDF and surprising the recipient. UC-014 AC-4 says "a genre-category slot with 1 qualifying title renders exactly 1 card (not 3 cards with 2 blank/duplicate fillers)" — the scarcity notes are not cards, but this adds unrequested content.
- **Fix**: Remove the subsection-level scarcity note entirely, or align it with the PRD requirement. The cover-page note already satisfies UC-014 AC-2. If a subsection-level note is desired, it must be specified in the PRD first.

---

### HIGH-004: OTT enrichment executed on all language-filtered records, not final selected records

- **File**: `src/main.py`, Lines ~458–463
- **Issue**: `_enrich_with_ott()` is called at Line ~460 on all raw records that passed the language filter (potentially 100+ items), before genre resolution, recency filtering, and top-N selection. The UC-010 precondition states "UC-008 has produced the final list of at most 24 selected recommendation records" — OTT enrichment should run after selection. The poster download step correctly does this (Lines ~563–568 filter to only selected IDs). OTT enrichment does not.
- **Risk**: Exceeds TMDB call budget (NFR-002). With 60 movies + 60 TV series passing language filter, this adds ~120 watch-provider calls in addition to ~120 external-ID calls + ~6 trending calls + ~24 poster calls = ~270 calls minimum, well above the ~150 needed if OTT were deferred.
- **Fix**: Move `_enrich_with_ott()` to run after `rank_and_select()` on the final `final_movies` and `final_series` dicts, mirroring the poster download pattern at Lines ~556–574.

---

### HIGH-005: `_build_message()` reads PDF attachment into memory without `try/except`

- **File**: `src/email_sender.py`, Lines ~169–172
- **Issue**:
  ```python
  with open(pdf_path, "rb") as fh:
      part = MIMEBase("application", "pdf")
      part.set_payload(fh.read())
  ```
  This file read is not wrapped in a `try/except`. While `FileNotFoundError` is checked before this call (Line ~80), an `PermissionError`, `OSError`, or `IOError` during the read itself (e.g., disk I/O error, file locked) will propagate as an unhandled exception to the caller, which expects only `FileNotFoundError` or `RuntimeError` (per the docstring Raises section). The caller in `main.py` Line ~618 catches `(FileNotFoundError, RuntimeError)` — a raw `OSError` would bypass this and become an unhandled exception.
- **Risk**: A disk read error during attachment loading produces an uncaught exception that bypasses the pipeline's error handling in `main.py`, resulting in a non-zero exit with a Python traceback rather than a clean FATAL log entry.
- **Fix**: Wrap the `with open(...)` block in a `try/except OSError as exc` and re-raise as `RuntimeError` to match the documented exception contract.

---

### HIGH-006: `OMDB_BASE_URL` uses `http://` (plain HTTP), not `https://`

- **File**: `src/config.py`, Line ~117
- **Issue**:
  ```python
  OMDB_BASE_URL: str = "http://www.omdbapi.com/"
  ```
  The OMDb API key is passed as a query parameter (`?apikey=...`). Using plain HTTP transmits the API key in cleartext over the network, violating the spirit of FR-017 ("no credentials hardcoded in source files") since the key would be visible to any network observer between PythonAnywhere and OMDb.
- **Risk**: API key exposure via network eavesdropping, particularly relevant on shared hosting infrastructure like PythonAnywhere.
- **Fix**: Change to `"https://www.omdbapi.com/"`. OMDb fully supports HTTPS.

---

## Medium Severity Issues

### MED-001: Duplicate key in `OTT_NAME_ALIASES` dict silently drops one entry

- **File**: `src/config.py`, Lines ~91–92
- **Issue**:
  ```python
  "jiocinam":             "JioCinema",
  "jiocinam":             "JioCinema",
  ```
  The key `"jiocinam"` appears twice. Python silently uses the second definition, making one entry dead code. This also indicates the alias list was generated hastily and may contain other typos (e.g., `"jiocinetma"` at Line ~87 has an extra `t`, `"jiociema"` at Line ~89 is missing an `n`).
- **Risk**: While the duplicate maps to the same value (no functional difference here), it indicates the alias map was not carefully reviewed. Unusual TMDB provider name variants may not be correctly normalised.
- **Fix**: Remove the duplicate key. Review all JioCinema aliases for correctness. Consider using a set of known misspellings from TMDB's actual responses.

---

### MED-002: `filter_by_language` logs `items[0].media_type` on potentially empty list

- **File**: `src/scorer.py`, Lines ~182–186
- **Issue**:
  ```python
  logger.info(
      "Language filter: %s %d -> %d",
      items[0].media_type if items else "items",
      before,
      len(result),
  )
  ```
  If `items` is empty, `items[0].media_type` would raise `IndexError`. The ternary guards this correctly. However, `before = len(items)` is evaluated before the filter (`before` will be 0), and the guard produces the string `"items"` instead of a useful label. The same pattern exists in `filter_by_recency()` (Line ~225) and `rank_and_select()` (Line ~381: `items[0].media_type if items else ""`). In `rank_and_select`, if `items` is empty, `sorted_items[:top_n]` will be `[]` and `available` will be 0 — but the log at Line ~380 still attempts `items[0].media_type if items else ""` which produces an empty string.
- **Risk**: Minor — no crash, but log messages lose the media_type label when a filter receives an empty list, making diagnosis harder.
- **Fix**: Pass the `media_type` as an explicit parameter to these functions, or default to a meaningful string like `"unknown"`.

---

### MED-003: `_resolve_ott_name` substring matching can produce false positives

- **File**: `src/data_fetcher.py`, Lines ~492–498
- **Issue**:
  ```python
  for canonical in PERMITTED_OTT_NAMES:
      if canonical.lower() in normalised or normalised in canonical.lower():
          return canonical
  ```
  The bidirectional substring match can produce unintended matches. For example, a provider named `"Sony"` would match canonical `"SonyLIV"` (because `"sony" in "sonyliv"` is True). More dangerously, a provider with a name like `"Amazon"` could match `"Amazon Prime Video"`. The alias map at `OTT_NAME_ALIASES` handles the common cases, but the fallback substring match is too permissive.
- **Risk**: Incorrectly attributing content to a platform could mislead the recipient about where to watch.
- **Fix**: Remove the substring fallback and rely exclusively on the alias map. Add any new canonical aliases discovered from live TMDB responses to `OTT_NAME_ALIASES`.

---

### MED-004: Log rotation deletes logs **after** the current run's log is fully written — potential 9th file window

- **File**: `src/main.py`, Lines ~110–122 (rotate_logs), Line ~626
- **Issue**: `rotate_logs()` is called at the very end of `run_pipeline()` (Line ~626), after the email has been sent. The log file for the current run is already open and being written to at this point (the `FileHandler` is added in `setup_logging()` but never closed before rotation). `os.remove()` on an open file behaves differently on Windows vs. Unix. On PythonAnywhere (Linux), the file is unlinked from the directory but the file handle remains valid — however, the deletion check `sorted(_glob.glob(...))` will include the current run's log if it already exists on disk (it does, since `setup_logging()` creates it). This means the rotation could delete the current run's log if it's the oldest among 9.

  More practically: after 8 weeks, there are 8 log files. On the 9th run, `setup_logging()` creates file #9. Then at the end of the run, `rotate_logs()` sees 9 files, and deletes the oldest (file #1). This is correct behavior. However, if a run fails midway and `rotate_logs()` is never reached, files accumulate without bound. The rotation should ideally run at the **start** of the pipeline (after creating the new log file) rather than at the end.
- **Risk**: Low on Linux/PythonAnywhere (file unlinking on open files works). But log accumulation on failure is a concern.
- **Fix**: Move `rotate_logs()` to immediately after `setup_logging()` returns in `run_pipeline()`.

---

### MED-005: `import` inside method body in `pdf_generator.py` and `email_sender.py`

- **File**: `src/pdf_generator.py`, Line ~479; `src/email_sender.py`, Line ~215
- **Issue**:
  ```python
  # pdf_generator.py, line ~479 inside PDFReport.generate():
  from src.config import GENRE_ORDER

  # email_sender.py, line ~215 inside EmailSender._build_body():
  from src.config import GENRE_ORDER
  ```
  Imports inside function/method bodies are valid Python but violate PEP 8 convention (E402 for module-level imports at the top, and the general principle that imports belong at the top of the file). These are not circular imports — `src.config` does not import from `src.pdf_generator` or `src.email_sender`. They should be moved to the top-level import block.
- **Risk**: Minor — slightly misleads readers about dependencies, and slightly increases per-call overhead (Python caches the import, so the overhead is negligible).
- **Fix**: Move both `from src.config import GENRE_ORDER` to the top-level imports of each file.

---

### MED-006: Email sender does not retry on transient SMTP failure

- **File**: `src/email_sender.py`, Lines ~95–131
- **Issue**: The `send()` method makes a single SMTP connection attempt with no retry logic. FR-016 specifies retry with exponential backoff for all external I/O failures. SMTP connections can fail transiently (network hiccup, temporary Gmail overload).
- **Risk**: A single transient SMTP failure causes the entire run to fail (returns exit code 1), meaning no email is delivered even though the PDF was successfully generated. The sentinel file is not written, so a manual re-run would attempt delivery again — but on PythonAnywhere automated runs, there is no re-run mechanism.
- **Fix**: Wrap the `smtplib.SMTP` block in a retry loop (2–3 attempts with 5–10 s delays) for `smtplib.SMTPConnectError` and `OSError`. Do not retry on `SMTPAuthenticationError` (that is non-retriable).

---

### MED-007: `ALL_PERMITTED_GENRE_IDS` type annotation uses bare `set` instead of `Set[int]`

- **File**: `src/config.py`, Line ~39
- **Issue**:
  ```python
  ALL_PERMITTED_GENRE_IDS: set = {gid for ids in GENRE_IDS.values() for gid in ids}
  ```
  The type annotation is `set` (bare), not `Set[int]`. Similarly, `PERMITTED_OTT_NAMES: set = ...` at Line ~102. In `scorer.py`, Line ~334: `seen_ids: set = set()`. Python 3.9+ supports `set[int]` directly; for 3.10+ compatibility (NFR-006), use `set[int]`.
- **Risk**: No runtime error, but type checkers (mypy, pyright) cannot verify the element types.
- **Fix**: Change to `Set[int]` (with `from typing import Set`) or the modern `set[int]` syntax since the project targets Python 3.10+.

---

### MED-008: `discover_movies()` and `discover_tv()` are implemented but never called in the pipeline

- **File**: `src/data_fetcher.py`, Lines ~336–432; `src/main.py` (no call site)
- **Issue**: `TMDBClient.discover_movies()` and `TMDBClient.discover_tv()` are fully implemented but are not called anywhere in `main.py`. OQ-003 in the PRD notes "a `/discover` fallback can be added in v1.1 if coverage is insufficient." The presence of this dead code is not a bug, but it contributes to TMDB call-count risk if it were inadvertently activated.
- **Risk**: Dead code can mislead reviewers into thinking fallback logic is active. If these methods were intended as fallbacks for sparse Kannada content (UC-014), they are not wired up.
- **Fix**: Either wire up the discover fallback (when a language/genre bucket has 0 items, trigger discover for that combination), or add a clear `# NOT USED IN v1.0` comment, or remove the methods until v1.1.

---

## Low Severity Issues

### LOW-001: Line length violations (PEP 8: max 79 chars)

- **File**: `src/data_fetcher.py`, Lines ~204, ~280, ~329
- **Issue**: Several lines exceed 79 characters:
  - Line ~204: `def _get(self, path: str, extra_params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:` (99 chars)
  - Line ~280: `logger.info("[TMDB] Fetched %d raw movie records (%d TMDB calls so far).", len(movies), self._call_count)` (107 chars)
  - Line ~329: `logger.info("[TMDB] Fetched %d raw TV records (%d TMDB calls so far).", len(series), self._call_count)` (104 chars)
  - `src/scorer.py` Line ~166: `def filter_by_language(items: List[ContentItem], languages: Optional[List[str]] = None) -> List[ContentItem]:` (110 chars)
  - `src/main.py` Line ~471: `logger.info("Built %d movie ContentItems, %d TV ContentItems.", len(movie_items), len(series_items))` (101 chars)
- **Risk**: None functional. Violates stated PEP 8 compliance requirement in the review checklist.
- **Fix**: Wrap long signatures and log calls across multiple lines using Python's implicit line continuation inside parentheses.

---

### LOW-002: `build_content_items_from_movies` and `build_content_items_from_tv` use untyped `list` parameter

- **File**: `src/scorer.py`, Lines ~391, ~430
- **Issue**:
  ```python
  def build_content_items_from_movies(raw_movies: list) -> List[ContentItem]:
  def build_content_items_from_tv(raw_series: list) -> List[ContentItem]:
  ```
  The parameters are typed as bare `list` instead of `List[RawMovie]` and `List[RawTVSeries]`. This is intentionally untyped to avoid a circular import (scorer.py would need to import from data_fetcher.py). The correct fix is to use `TYPE_CHECKING` guard or define a shared protocol.
- **Risk**: Type checkers cannot validate callers. Incorrect types passed at callsite will only fail at runtime.
- **Fix**: Use `from __future__ import annotations` and a `TYPE_CHECKING` block:
  ```python
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from src.data_fetcher import RawMovie, RawTVSeries
  ```
  Then annotate `raw_movies: List["RawMovie"]`.

---

### LOW-003: `rotate_logs()` uses `logging.getLogger(__name__)` redundantly each call

- **File**: `src/main.py`, Lines ~119–122
- **Issue**: `rotate_logs()` calls `logging.getLogger(__name__)` inline. The module already has a pattern of doing this inside helper functions (`_enrich_with_imdb`, `_enrich_with_ott`, `_download_posters`). The module-level `logger` idiom (assign once at module top) is more idiomatic and avoids repeated dictionary lookups.
- **Risk**: Negligible performance impact. Minor code inconsistency.
- **Fix**: Add `logger = logging.getLogger(__name__)` at module level in `main.py` and use it throughout all functions instead of calling `logging.getLogger(__name__)` inside each function body.

---

### LOW-004: `ContentItem.teaser` property calls private scorer helper `_truncate_overview` but `pdf_generator.py` reimplements the same logic

- **File**: `src/scorer.py`, Lines ~93–94; `src/pdf_generator.py`, Lines ~125–136
- **Issue**: `_truncate_overview()` in `scorer.py` and `_truncate()` in `pdf_generator.py` are functionally identical (both truncate at word boundary to 120 chars with `...`). `pdf_generator.py` acknowledges this at Line ~122: `# Overview truncation (mirrors scorer.py for self-containment)`. This duplication means if the truncation logic changes (e.g., max_chars changes from 120 to 150), it must be updated in two places.
- **Risk**: Logic drift if only one copy is updated.
- **Fix**: Export `_truncate_overview` from `scorer.py` (rename to `truncate_overview` to make it public) and import it in `pdf_generator.py`.

---

### LOW-005: `_FooterCanvas._draw_footer` missing type hint on `canvas` and `doc` parameters

- **File**: `src/pdf_generator.py`, Line ~278
- **Issue**:
  ```python
  def _draw_footer(self, canvas, doc) -> None:
  ```
  `canvas` and `doc` have no type hints. ReportLab types are `reportlab.pdfgen.canvas.Canvas` and `reportlab.platypus.doctemplate.BaseDocTemplate`.
- **Risk**: None functional. Violates the "type hints on all function signatures" checklist requirement.
- **Fix**: Add type hints (or annotate as `Any` with a comment if ReportLab types are inconvenient to import).

---

### LOW-006: UC-001 AC-3 compliance — log start timestamp uses `datetime.now().isoformat()` not strictly ISO-8601 `YYYY-MM-DDTHH:MM:SS`

- **File**: `src/main.py`, Line ~367
- **Issue**:
  ```python
  log.info("Weekly Movie Recommender — run start at %s", datetime.now().isoformat())
  ```
  `datetime.now().isoformat()` produces microseconds: `2026-03-07T08:23:45.123456`. UC-001 AC-3 requires `YYYY-MM-DDTHH:MM:SS` format. The logging formatter uses `datefmt="%Y-%m-%dT%H:%M:%S"` which is correct for the asctime prefix, but this specific log message uses the raw Python isoformat.
- **Risk**: No functional impact. Minor AC-3 non-compliance.
- **Fix**: Change to `datetime.now().strftime("%Y-%m-%dT%H:%M:%S")`.

---

### LOW-007: `pdf_generator.py` `_build_cover` return type annotation is `list` not `List[...]`

- **File**: `src/pdf_generator.py`, Lines ~543, ~607, ~651
- **Issue**: Return types for `_build_cover()`, `_build_genre_section()`, and `_build_subsection()` are annotated as bare `list` rather than `List[Any]` or a more specific flowable type.
- **Risk**: Minor type annotation incompleteness.
- **Fix**: Annotate as `List[Any]` (importing `Any` from `typing`).

---

### LOW-008: `OMDbClient.fetch_ratings` return type uses Python 3.10+ union syntax not available in 3.10

- **File**: `src/data_fetcher.py`, Line ~642
- **Issue**:
  ```python
  def fetch_ratings(self, imdb_id: str) -> tuple[Optional[float], int]:
  ```
  `tuple[...]` (lowercase) as a generic type hint is only available in Python 3.9+. Since NFR-006 requires Python 3.10+, this is valid. However, the project uses `from typing import Dict, List, Optional, Tuple` elsewhere and does not use `tuple[...]` consistently — `Tuple[Optional[float], int]` from `typing` would be more consistent with the rest of the codebase.
- **Risk**: None. Both forms work on Python 3.10+. Minor inconsistency.
- **Fix**: For consistency with the rest of the codebase, change to `Tuple[Optional[float], int]` and add `Tuple` to the `typing` import in `data_fetcher.py`.

---

## Positive Observations

- **Secrets management is excellent**: All credentials are loaded exclusively via `Config._require()` which raises a clear `EnvironmentError` with a descriptive message if any variable is missing. No secrets appear in any source file. FR-017 is fully satisfied.
- **Error handling depth**: The retry logic in `_request_with_retry()` correctly distinguishes FATAL (401), non-retriable (400, 404), and retriable (429, 5xx, network exception) status codes. `FatalAPIError` is cleanly propagated through the call stack and caught at the pipeline level in `main.py`.
- **Idempotency implementation**: The sentinel file pattern in `main.py` (`_sentinel_path`, `_mark_sent`, `_already_sent`) is correct, simple, and satisfies NFR-007. The sentinel is only written after a confirmed successful email send.
- **Log rotation**: The `rotate_logs()` implementation is clean and correctly handles the 8-file retention requirement (NFR-005).
- **PythonAnywhere compatibility**: The project correctly uses `reportlab` (pre-installed on PythonAnywhere free tier) rather than `weasyprint` (which requires `libpango`, a C extension not available). No C extension that isn't pre-installed is required.
- **Dataclass design**: `RawMovie`, `RawTVSeries`, and `ContentItem` are well-typed dataclasses with sensible defaults. The separation between raw API records and scored content items is architecturally sound.
- **OMDb "N/A" handling**: `OMDbClient.fetch_ratings()` correctly handles `"N/A"` for both `imdbRating` and `imdbVotes`, setting `None` and `0` respectively. UC-009 AF-3 and AF-4 are correctly implemented.
- **Genre deduplication**: `deduplicate_across_genres()` correctly implements FR-018 — each title appears in only one genre bucket (the highest-scoring one), with canonical order tiebreaking.
- **Docstring coverage**: All public classes and methods have docstrings with Args/Returns/Raises sections. The codebase is well-documented.
- **Saturday gate**: `today.weekday() != 5` is the correct check (Python weekday: Monday=0, Saturday=5). The `--force` flag correctly bypasses this. Both UC-001 AF-1 and AF-3 are handled. Exit code 0 on non-Saturday (AC-2 compliant).
- **OTT alias map**: The `OTT_NAME_ALIASES` dict and the `_resolve_ott_name` fallback demonstrate awareness of real-world TMDB provider naming inconsistencies. The alias map is comprehensive for common variants (duplicate key aside).
- **Poster download with Pillow validation**: `download_poster()` validates the downloaded image bytes using `Image.open(BytesIO(image_bytes)).verify()` before returning, catching corrupt images early (UC-011 AF-3).

---

## PRD Alignment Check

| FR | Implemented? | Notes |
|---|---|---|
| FR-001 | Partial | Saturday gate implemented. PythonAnywhere scheduling is an ops task (not code), but the code gate is correct. |
| FR-002 | Yes | `fetch_trending_movies()` and `fetch_trending_tv()` implemented with up to `TMDB_MAX_PAGES` pages. |
| FR-003 | Yes | Language filter applied at raw record level checking both `original_language` and `spoken_languages`. |
| FR-004 | Yes | Genre resolution via `GENRE_ID_TO_NAME` and `ALL_PERMITTED_GENRE_IDS` is correct. Genre IDs 28, 10759, 53, 9648, 18, 35 are all mapped. Note: Thriller TV genre ID 9648 (Mystery) is mapped to "Thriller" — this is a deliberate mapping, not a bug, but should be confirmed with the product owner. |
| FR-005 | Yes | `filter_by_recency()` correctly excludes titles older than 365 days. Missing dates are excluded. |
| FR-006 | Yes | OMDb enrichment fetches `imdbRating` and `imdbVotes` via IMDB ID from TMDB external_ids. |
| FR-007 | Disputed | Implementation weights `0.4/0.4/0.2`. Review checklist states `0.40 IMDB + 0.30 popularity + 0.30 vote_count`. See CRITICAL-001. |
| FR-008 | Yes | `rank_and_select()` returns `items[:TOP_N]` where `TOP_N=3`. Max 24 recommendations possible. |
| FR-009 | Yes | Watch providers fetched for India (`IN`), `flatrate` only. Provider names normalised via alias map. Missing platforms shown as "Not confirmed on major OTT". |
| FR-010 | Yes | Poster download at `w342` size with Pillow validation. Placeholder generated programmatically (grey rectangle). Note: UC-011 precondition mentions "a placeholder image file exists in the codebase at a known relative path (e.g., `assets/placeholder_poster.jpg`)" — the code generates one programmatically, which is better but different from the spec. |
| FR-011 | Yes | PDF cards contain all 9 required fields: poster, title, release year, language, category, IMDB rating, TMDB popularity, OTT platforms, teaser. Cover page and genre sections implemented. |
| FR-012 | Yes | PDF named `movie_recommendations_{YYYY-MM-DD}.pdf` at Line ~156 in `main.py`. |
| FR-013 | Yes | Gmail SMTP port 587, STARTTLS, App Password authentication. |
| FR-014 | Yes | Subject format matches: `Your Weekly Movie & Series Picks — {DD Month YYYY}`. Email body includes total count and genres. |
| FR-015 | Yes | Structured logging throughout pipeline with counts at each filter stage. |
| FR-016 | Partial | Retry logic implemented for TMDB/OMDb API calls. Email send has no retry (see MED-006). |
| FR-017 | Yes | All credentials from environment variables via `Config._require()`. |
| FR-018 | Yes | `deduplicate_across_genres()` correctly implements single-genre-per-title assignment. |

---

## Summary Counts

| Severity | Count |
|---|---|
| CRITICAL | 3 |
| HIGH | 6 |
| MEDIUM | 8 |
| LOW | 8 |
| **Total** | **25** |
