# Use Cases: Weekly Movie & Web Series Recommender

**Version:** 1.0
**Date:** 2026-03-01
**Status:** Draft
**Linked PRD:** PRD.md v1.0

---

## Overview

This document specifies all 15 use cases for the Weekly Movie & Web Series Recommender system. The system is fully automated with no human-in-the-loop during execution. The primary actor for every use case is **System** (the automated pipeline). The **Report Recipient** (Ketan's wife) interacts only with the final email and PDF artifact — she never triggers or configures the system. The **System Operator** (Ketan) interacts only during setup and maintenance.

### Actor Definitions

| Actor | Role |
|---|---|
| **System** | The automated Python pipeline running on PythonAnywhere scheduled tasks. |
| **System Operator** | Ketan — sets up, configures, and monitors the service; does not interact during a run. |
| **Report Recipient** | Ketan's wife — receives and reads the weekly PDF email; requires no technical knowledge. |

### Priority Definitions

| Priority | Meaning |
|---|---|
| **Critical** | Without this, the entire pipeline cannot produce any output. |
| **High** | Without this, output is produced but is materially incomplete or incorrect. |
| **Medium** | Affects quality, resilience, or coverage but does not break the pipeline. |
| **Low** | Handles edge cases; degradation is graceful and acceptable for v1.0. |

### Use Case Index

| ID | Title | Priority |
|---|---|---|
| UC-001 | Saturday scheduling gate | Critical |
| UC-002 | Fetch trending movies (TMDB, India) | Critical |
| UC-003 | Fetch trending web series (TMDB, India) | Critical |
| UC-004 | Filter by language (hi/en/kn) | Critical |
| UC-005 | Filter by genre (Action/Thriller/Drama/Comedy) | Critical |
| UC-006 | Filter by recency (≤ 365 days old) | Critical |
| UC-007 | Composite score and rank content | Critical |
| UC-008 | Select top 3 per genre per category | High |
| UC-009 | Enrich with IMDB rating via OMDb | High |
| UC-010 | Fetch India OTT availability (TMDB Watch Providers, country=IN) | High |
| UC-011 | Download poster thumbnail images | Medium |
| UC-012 | Generate PDF report (cover + genre cards) | Critical |
| UC-013 | Email PDF to recipient via Gmail SMTP | Critical |
| UC-014 | Handle sparse Kannada content gracefully | Medium |
| UC-015 | Handle API failures gracefully (retry + fallback + logging) | High |

---

## Use Cases

---

### UC-001: Saturday Scheduling Gate

**ID**: UC-001
**Actor**: System
**Priority**: Critical
**Related FRs**: FR-001, FR-015, NFR-007

**Preconditions**:
- PythonAnywhere scheduled task is configured and active for the system operator's account.
- The system's clock is set to IST (UTC+5:30) or the scheduled task accounts for the UTC offset.
- All environment variables and credentials are present in the `.env` file or PythonAnywhere task environment before the scheduled window begins.

**Main Flow**:
1. PythonAnywhere's scheduler triggers the pipeline at a time between 07:00 and 09:00 IST on a Saturday.
2. The system reads the current system date and verifies that the weekday is Saturday (ISO weekday = 6).
3. The system records the run start timestamp in the execution log.
4. The system proceeds to UC-002 (fetch trending movies) and UC-003 (fetch trending web series).

**Alternate Flows**:
- AF-1: Scheduler fires on a non-Saturday (e.g., clock drift, misconfiguration) — the system checks the weekday, logs a warning entry with the detected weekday name and ISO date, and exits without fetching data or sending any email.
- AF-2: The scheduled task fires but environment variables are missing or unreadable — the system logs a FATAL error specifying which variable is absent and exits immediately without making any external API calls.
- AF-3: The pipeline is triggered manually by the operator on a non-Saturday for testing — behavior is identical to AF-1 unless the operator sets an override flag; this is acceptable in v1.0 without an override mechanism.

**Postconditions**:
- If the day is Saturday: the pipeline is running and a start-time entry exists in the execution log.
- If the day is not Saturday: the process has exited cleanly and a single warning-level log entry records the skipped run.

**Acceptance Criteria**:
- AC-1: When the system clock reports a Saturday, the pipeline proceeds past the scheduling gate and at least one TMDB API call is made within the same execution.
- AC-2: When the system clock reports any day other than Saturday, no TMDB API call, no OMDb API call, no PDF file, and no email are produced, and the exit code is 0 (clean exit, not a crash).
- AC-3: The execution log contains a start timestamp entry with ISO-8601 format (YYYY-MM-DDTHH:MM:SS) for every triggered run regardless of day.
- AC-4: Running the pipeline twice on the same Saturday does not produce two emails; the second run detects that a report for that date already exists and skips email delivery, satisfying NFR-007 (idempotency).

---

### UC-002: Fetch Trending Movies (TMDB, India)

**ID**: UC-002
**Actor**: System
**Priority**: Critical
**Related FRs**: FR-002, FR-015, FR-016, FR-017, NFR-002

**Preconditions**:
- UC-001 has passed (it is Saturday and the pipeline is running).
- `TMDB_API_KEY` environment variable is set to a valid TMDB v3 API key.
- The system has outbound HTTPS access to `api.themoviedb.org` on port 443.

**Main Flow**:
1. The system constructs a GET request to `https://api.themoviedb.org/3/trending/movie/week` with the query parameter `api_key={TMDB_API_KEY}`.
2. The system sends the request and receives a JSON response containing a `results` array of trending movie objects.
3. The system checks the `total_pages` field in the response; if more than 1 page exists, it fetches subsequent pages by appending `&page={n}` until all pages are retrieved or the 500-request budget (NFR-002) would be exceeded.
4. For each movie object in the combined results array, the system stores at minimum: `id`, `title`, `original_language`, `spoken_languages`, `genre_ids`, `release_date`, `popularity`, `overview`, `poster_path`.
5. The system logs the total number of raw movie records fetched.
6. The system passes the raw movie list to UC-004 (language filter), UC-005 (genre filter), and UC-006 (recency filter).

**Alternate Flows**:
- AF-1: The TMDB API returns HTTP 401 (invalid API key) — the system logs a FATAL error with the HTTP status code and the endpoint URL, then exits without attempting any further API calls or generating a PDF.
- AF-2: The TMDB API returns HTTP 429 (rate limit exceeded) — the system treats this as a retriable error and applies exponential backoff per UC-015 (1s, 2s, 4s delays before each retry attempt).
- AF-3: The TMDB API returns HTTP 5xx — the system applies the retry logic from UC-015; if all 3 retries fail, it logs the failure and continues with whatever movie records have already been fetched from earlier pages.
- AF-4: The response JSON is malformed or missing the `results` key — the system logs an ERROR with the raw response body (truncated to 500 characters) and treats the fetch as returning zero results.
- AF-5: Fetching additional pages would exceed the 500-request budget — the system stops pagination, logs a warning with the page number reached, and proceeds with the records collected so far.

**Postconditions**:
- A list of raw movie objects (possibly empty) is held in memory for downstream filtering.
- The execution log contains an entry stating the number of raw movie records fetched and the number of TMDB API calls made.

**Acceptance Criteria**:
- AC-1: Given a valid TMDB API key, the system fetches at least 20 movie records (TMDB's default page size) from the trending endpoint on a normal Saturday run.
- AC-2: The system stores `id`, `title`, `original_language`, `genre_ids`, `release_date`, `popularity`, and `poster_path` for every fetched movie record; any record missing `id` or `title` is discarded and counted in the log.
- AC-3: The system does not make more than 500 TMDB API calls in total across UC-002 and UC-003 combined during a single run, verifiable by counting log entries tagged `[TMDB_CALL]`.
- AC-4: A FATAL log entry with HTTP status 401 causes the pipeline to exit without producing a PDF or sending an email.
- AC-5: No TMDB credentials appear in any log file or in the PDF output.

---

### UC-003: Fetch Trending Web Series (TMDB, India)

**ID**: UC-003
**Actor**: System
**Priority**: Critical
**Related FRs**: FR-002, FR-015, FR-016, FR-017, NFR-002

**Preconditions**:
- UC-001 has passed (it is Saturday and the pipeline is running).
- `TMDB_API_KEY` environment variable is set to a valid TMDB v3 API key.
- The system has outbound HTTPS access to `api.themoviedb.org` on port 443.

**Main Flow**:
1. The system constructs a GET request to `https://api.themoviedb.org/3/trending/tv/week` with the query parameter `api_key={TMDB_API_KEY}`.
2. The system sends the request and receives a JSON response containing a `results` array of trending TV series objects.
3. The system checks the `total_pages` field; if more than 1 page exists, it fetches subsequent pages by appending `&page={n}` until all pages are retrieved or the combined TMDB API budget of 500 requests (NFR-002, shared with UC-002) would be exceeded.
4. For each TV series object, the system stores at minimum: `id`, `name`, `original_language`, `spoken_languages`, `genre_ids`, `first_air_date`, `popularity`, `overview`, `poster_path`.
5. The system logs the total number of raw TV series records fetched.
6. The system passes the raw TV series list to UC-004, UC-005, and UC-006.

**Alternate Flows**:
- AF-1: HTTP 401 from TMDB — same behavior as UC-002 AF-1: FATAL log and pipeline exit.
- AF-2: HTTP 429 from TMDB — retry per UC-015 exponential backoff.
- AF-3: HTTP 5xx from TMDB — retry per UC-015; on persistent failure, log error and continue with already-fetched records.
- AF-4: Malformed JSON response — log ERROR with truncated raw body, treat as zero results for this endpoint.
- AF-5: The `first_air_date` field is absent on a TV series record — the system treats the date as unknown, which causes the record to be excluded by UC-006 (recency filter) since the date cannot be verified.
- AF-6: A TV series record has `media_type` set to something other than `tv` — the record is discarded and counted in the log.

**Postconditions**:
- A list of raw TV series objects (possibly empty) is held in memory for downstream filtering, separate from the movie list.
- The execution log contains an entry stating the number of raw TV series records fetched.

**Acceptance Criteria**:
- AC-1: Given a valid TMDB API key, the system fetches at least 20 TV series records from the trending TV endpoint on a normal run.
- AC-2: Web series records are stored and processed in a collection separate from movies throughout the pipeline; no movie record is placed in the web series collection and vice versa.
- AC-3: Records with a missing or null `first_air_date` are excluded from downstream processing and counted as "excluded — no date" in the log.
- AC-4: The system correctly reads the display title from the `name` field (not `title`) for TV series records.
- AC-5: The combined TMDB API call count across UC-002 and UC-003 does not exceed 500, verifiable from log entries.

---

### UC-004: Filter by Language (hi/en/kn)

**ID**: UC-004
**Actor**: System
**Priority**: Critical
**Related FRs**: FR-003, FR-015

**Preconditions**:
- UC-002 and UC-003 have produced raw lists of movie and TV series objects.
- The permitted language codes are statically configured as `['hi', 'en', 'kn']`.

**Main Flow**:
1. The system iterates over each record in the raw movie list and each record in the raw TV series list.
2. For each record, the system extracts the `original_language` field and the `spoken_languages` array (which contains objects with an `iso_639_1` field).
3. The system checks whether `original_language` is in `['hi', 'en', 'kn']` OR whether any entry in `spoken_languages` has `iso_639_1` in `['hi', 'en', 'kn']`.
4. Records that satisfy either condition pass the language filter; all other records are discarded.
5. The system logs the count of records before and after the language filter for each category (movies and TV series separately).

**Alternate Flows**:
- AF-1: A record has `original_language` set to `null` or is absent — the system checks only the `spoken_languages` array; if that is also absent or empty, the record is excluded.
- AF-2: A record has `spoken_languages` as an empty array — the system falls back to `original_language` only for the language check.
- AF-3: All records are excluded by the language filter — the system logs a WARNING that zero records passed language filtering for the affected category, continues processing (the genre and recency filters will receive an empty list), and the PDF will reflect zero results for that category.

**Postconditions**:
- Two filtered lists exist in memory (movies and TV series), each containing only records with `original_language` or a `spoken_languages` entry in `['hi', 'en', 'kn']`.
- The execution log contains before-count and after-count for the language filter stage for each category.

**Acceptance Criteria**:
- AC-1: A movie record with `original_language = 'ta'` (Tamil) and no Hindi/English/Kannada spoken language is not present in the language-filtered output list.
- AC-2: A movie record with `original_language = 'ta'` but `spoken_languages` containing `{'iso_639_1': 'hi'}` is retained in the language-filtered output list.
- AC-3: A movie record with `original_language = 'kn'` is retained in the language-filtered output list.
- AC-4: The execution log contains exactly two count entries for language filtering — one for movies and one for TV series — in a format such as "Language filter: movies 80 -> 23, tv 80 -> 19".
- AC-5: No record with a language code outside `['hi', 'en', 'kn']` (and no qualifying spoken language) appears anywhere in the final PDF report.

---

### UC-005: Filter by Genre (Action/Thriller/Drama/Comedy)

**ID**: UC-005
**Actor**: System
**Priority**: Critical
**Related FRs**: FR-004, FR-015, FR-018

**Preconditions**:
- UC-004 has produced language-filtered lists of movies and TV series.
- The permitted genre IDs are statically configured: Action = 28 (movie) / 10759 (TV), Thriller = 53, Drama = 18, Comedy = 35.

**Main Flow**:
1. The system iterates over each record in the language-filtered movie list and TV series list.
2. For each record, the system extracts the `genre_ids` array.
3. The system checks whether `genre_ids` contains at least one value from the permitted set: `{28, 10759, 53, 18, 35}`.
4. Records whose `genre_ids` intersect with the permitted set pass the genre filter; all others are discarded.
5. For each passing record, the system resolves and stores the human-readable genre names for every matching permitted genre (a single title may qualify under multiple genres).
6. The system applies deduplication per FR-018: if a title qualifies under multiple permitted genres, it is tagged with all qualifying genres but will ultimately appear only under the genre with the highest composite score (deduplication is enforced in UC-008 after scoring).
7. The system logs the count of records before and after the genre filter for each category.

**Alternate Flows**:
- AF-1: A record has `genre_ids` as an empty array — the record is excluded by the genre filter and counted as "excluded — no genre" in the log.
- AF-2: A record has `genre_ids` containing only genre IDs outside the permitted set (e.g., Horror id 27, Documentary id 99) — the record is excluded.
- AF-3: All records are excluded by the genre filter — the system logs a WARNING and continues with empty lists for downstream steps.

**Postconditions**:
- Two genre-filtered lists exist in memory (movies and TV series) where every record has at least one qualifying genre tag.
- Each record carries a `qualifying_genres` attribute listing all permitted genres it matched.
- The execution log contains before-count and after-count for genre filtering for each category.

**Acceptance Criteria**:
- AC-1: A movie with `genre_ids = [27, 12]` (Horror, Adventure) is not present in the genre-filtered output.
- AC-2: A movie with `genre_ids = [28, 12]` (Action, Adventure) is present in the genre-filtered output and is tagged with `qualifying_genres = ['Action']`.
- AC-3: A TV series with `genre_ids = [10759, 18]` (Action & Adventure TV, Drama) is present and tagged with `qualifying_genres = ['Action', 'Drama']`.
- AC-4: The execution log contains genre filter count entries for both movies and TV series.
- AC-5: No record in the final PDF report belongs to a genre outside Action, Thriller, Drama, or Comedy.

---

### UC-006: Filter by Recency (≤ 365 Days Old)

**ID**: UC-006
**Actor**: System
**Priority**: Critical
**Related FRs**: FR-005, FR-015

**Preconditions**:
- UC-005 has produced genre-filtered lists of movies and TV series.
- The execution date (Saturday date) is known.
- For movies, the relevant date field is `release_date`; for TV series, it is `first_air_date`.

**Main Flow**:
1. The system records the execution date as `today` (the Saturday run date, in YYYY-MM-DD format).
2. The system iterates over each record in the genre-filtered movie list.
3. For each movie record, the system parses the `release_date` string as a date.
4. The system computes `age_days = (today - release_date).days`.
5. If `age_days <= 365`, the record passes the recency filter; otherwise it is discarded.
6. The system repeats steps 3-5 for each TV series record using `first_air_date`.
7. The system logs the count of records before and after the recency filter for each category.

**Alternate Flows**:
- AF-1: `release_date` or `first_air_date` is an empty string or `null` — the system treats the date as unknown, excludes the record, and logs it as "excluded — missing date".
- AF-2: The date string is present but cannot be parsed (e.g., partial date "2025" or non-standard format) — the system excludes the record and logs "excluded — unparseable date: {value}".
- AF-3: `release_date` is in the future (pre-release title appearing in trending) — `age_days` would be negative; the record passes the recency filter since it is clearly recent (age < 365).
- AF-4: All records are excluded by the recency filter — the system logs a WARNING and continues with empty lists.

**Postconditions**:
- Two recency-filtered lists exist in memory where every record has a verified `release_date` or `first_air_date` within 365 days of the execution date.
- The execution log contains before-count and after-count for the recency filter for each category.

**Acceptance Criteria**:
- AC-1: A movie with `release_date = {execution_date - 365 days}` (exactly 365 days old) is retained in the recency-filtered output.
- AC-2: A movie with `release_date = {execution_date - 366 days}` (366 days old) is excluded from the recency-filtered output.
- AC-3: A movie with `release_date = null` is excluded and logged as "excluded — missing date".
- AC-4: A TV series with `first_air_date = {execution_date - 100 days}` is retained.
- AC-5: The execution log contains recency filter count entries (e.g., "Recency filter: movies 23 -> 18, tv 19 -> 14") for every run.
- AC-6: The final PDF contains no title whose release year is more than 1 year before the Saturday execution date (verifiable by spot-checking 5 random titles from the report).

---

### UC-007: Composite Score and Rank Content

**ID**: UC-007
**Actor**: System
**Priority**: Critical
**Related FRs**: FR-006, FR-007, FR-015, NFR-003

**Preconditions**:
- UC-006 has produced recency-filtered lists of movies and TV series.
- UC-009 (OMDb enrichment) has been called to attach `imdb_rating` and `imdb_vote_count` to each record; records that failed OMDb enrichment have `imdb_rating = None` and `imdb_vote_count = 0`.
- Each record already carries `tmdb_popularity` from the TMDB response.

**Main Flow**:
1. The system iterates over each record in the filtered movie list and TV series list.
2. For each record, the system applies the composite score formula:
   `Score = (tmdb_popularity * 0.4) + (imdb_rating * 10 * 0.4) + (log10(imdb_vote_count + 1) * 0.2)`
3. If `imdb_rating` is `None` (no OMDb data), the IMDB component is treated as `0` (i.e., `0 * 10 * 0.4 = 0`).
4. The system stores the computed score on the record as `composite_score` (rounded to 4 decimal places).
5. The system sorts each category's list (movies, TV series) by `composite_score` descending — independently for each qualifying genre.
6. The system logs the top-scoring title per genre per category with its composite score for audit purposes.

**Alternate Flows**:
- AF-1: `tmdb_popularity` is `null` or missing on a record — the system treats it as `0.0` for the formula and logs the anomaly.
- AF-2: `imdb_vote_count` is `0` — `log10(0 + 1) = log10(1) = 0`, so the log component contributes `0`; this is mathematically correct and requires no special handling.
- AF-3: `imdb_vote_count` is negative (data anomaly) — the system clamps it to `0` before applying the formula and logs the anomaly.
- AF-4: Two records have identical composite scores — the system uses `tmdb_popularity` as a tiebreaker (higher popularity wins); if still equal, the record with the alphabetically earlier title is ranked first.

**Postconditions**:
- Every record in the filtered lists has a `composite_score` value (a non-negative float).
- Records within each genre bucket are ordered by `composite_score` descending.
- The execution log contains the top composite score per genre per category.

**Acceptance Criteria**:
- AC-1: Given a movie with `tmdb_popularity = 100.0`, `imdb_rating = 7.5`, `imdb_vote_count = 10000`, the system computes `composite_score = (100.0 * 0.4) + (7.5 * 10 * 0.4) + (log10(10001) * 0.2) = 40.0 + 30.0 + (4.0001 * 0.2) = 70.8` (approximately 70.8000), verifiable by unit test.
- AC-2: Given a movie with `imdb_rating = None`, the system computes `composite_score = (tmdb_popularity * 0.4) + 0 + (log10(imdb_vote_count + 1) * 0.2)` without raising an exception.
- AC-3: Within a single genre bucket, records are sorted so that the record with the highest `composite_score` is at index 0.
- AC-4: Two records with identical composite scores are ordered by descending `tmdb_popularity`; if `tmdb_popularity` is also identical, they are ordered alphabetically by title.
- AC-5: The log contains one composite-score summary line per genre per category (maximum 8 lines: 4 genres x 2 categories).

---

### UC-008: Select Top 3 Per Genre Per Category

**ID**: UC-008
**Actor**: System
**Priority**: High
**Related FRs**: FR-008, FR-015, FR-018

**Preconditions**:
- UC-007 has produced scored and ranked records grouped by genre for each category (movies, TV series).
- The deduplication rule from FR-018 is enforced: each title appears in at most one genre bucket (the one with the highest composite score).

**Main Flow**:
1. The system applies deduplication across genre buckets: for each title that appears in more than one genre bucket, it is removed from all buckets except the one in which it achieved its highest `composite_score`. Ties in composite score across genres are broken by selecting the genre that appears first in the canonical order: Action, Thriller, Drama, Comedy.
2. For each of the 4 genres (Action, Thriller, Drama, Comedy) and each of the 2 categories (Movies, Web Series), the system takes the top `min(3, N)` records from the ranked bucket, where `N` is the number of qualifying records in that bucket after deduplication.
3. The system assembles the final recommendation list: at most 3 movies per genre (at most 12 total movie slots) and at most 3 web series per genre (at most 12 total web series slots), for a maximum of 24 recommendations per report.
4. The system logs for each genre-category combination: the number of qualifying records available and the number selected.

**Alternate Flows**:
- AF-1: A genre-category combination has 0 qualifying records — the system logs "0 titles selected for {genre} {category}" and omits that genre section from the PDF for that category, or renders the section header with a note "No qualifying titles this week."
- AF-2: A genre-category combination has fewer than 3 qualifying records (e.g., only 1 or 2) — the system selects all available records (1 or 2) without padding; the report card count for that section will be 1 or 2 rather than 3.
- AF-3: After deduplication, a title moves out of a bucket, causing a previously 4th-ranked title to become 3rd — the system correctly selects the newly promoted 3rd-ranked title.

**Postconditions**:
- A final recommendation list of at most 24 records exists in memory, split by genre and category.
- Each record appears in exactly one genre bucket.
- The execution log records the slot-fill count per genre per category.

**Acceptance Criteria**:
- AC-1: If a genre-category bucket contains 5 qualifying titles after deduplication, exactly 3 are selected (the top-3 by composite score).
- AC-2: If a genre-category bucket contains 2 qualifying titles after deduplication, exactly 2 are selected (not padded with empty cards or duplicates).
- AC-3: No title appears in more than one genre section within the final recommendation list.
- AC-4: The maximum possible total recommendations in a single report is 24 (4 genres x 3 titles x 2 categories); the system never selects more than 3 per genre per category.
- AC-5: The execution log contains a line per genre per category stating "Selected {n} of {available} for {genre} {category}" (e.g., "Selected 3 of 7 for Action Movies").
- AC-6: On a test run where Genre A has 5 qualified titles — one of which also qualifies for Genre B with a higher score in Genre A — that title appears in Genre A only, and Genre B receives the next best title not already assigned.

---

### UC-009: Enrich with IMDB Rating via OMDb

**ID**: UC-009
**Actor**: System
**Priority**: High
**Related FRs**: FR-006, FR-007, FR-015, FR-016, FR-017, NFR-003

**Preconditions**:
- UC-004, UC-005, UC-006 have produced filtered lists (language, genre, recency) of movies and TV series candidates.
- `OMDB_API_KEY` environment variable is set to a valid OMDb API key.
- The system has outbound HTTPS access to `www.omdbapi.com` on port 443.
- Each candidate record has a TMDB `id` that can be used to retrieve the IMDB ID.

**Main Flow**:
1. For each candidate record, the system makes a GET request to the TMDB external IDs endpoint:
   - Movies: `https://api.themoviedb.org/3/movie/{id}/external_ids?api_key={TMDB_API_KEY}`
   - TV Series: `https://api.themoviedb.org/3/tv/{id}/external_ids?api_key={TMDB_API_KEY}`
2. The system extracts the `imdb_id` field from the TMDB response (e.g., `"tt1234567"`).
3. If `imdb_id` is present and non-null, the system makes a GET request to: `http://www.omdbapi.com/?i={imdb_id}&apikey={OMDB_API_KEY}`
4. The system parses the OMDb JSON response and extracts `imdbRating` (a decimal string, e.g., `"7.5"`) and `imdbVotes` (a comma-formatted integer string, e.g., `"123,456"`).
5. The system converts `imdbRating` to a float and `imdbVotes` to an integer (stripping commas).
6. The system attaches `imdb_rating` (float or `None`) and `imdb_vote_count` (int, defaulting to 0) to the candidate record.
7. The system logs the total number of OMDb calls made and the number of records for which IMDB data was successfully retrieved.

**Alternate Flows**:
- AF-1: TMDB external IDs endpoint returns no `imdb_id` (field is null or absent) — the system skips the OMDb call for this record, sets `imdb_rating = None` and `imdb_vote_count = 0`, and logs "No IMDB ID for TMDB ID {id}".
- AF-2: OMDb returns `{"Response": "False", "Error": "Movie not found!"}` — the system sets `imdb_rating = None` and `imdb_vote_count = 0` for the record and logs "OMDb not found for IMDB ID {imdb_id}".
- AF-3: OMDb returns `imdbRating = "N/A"` — the system treats this as no rating and sets `imdb_rating = None`.
- AF-4: OMDb returns `imdbVotes = "N/A"` — the system sets `imdb_vote_count = 0`.
- AF-5: The OMDb API call fails after 3 retries (per UC-015) — the system sets `imdb_rating = None` and `imdb_vote_count = 0` for the affected record, logs the failure, and continues with the next candidate.
- AF-6: OMDb returns HTTP 401 (invalid API key) — the system logs a FATAL error and exits the pipeline immediately.
- AF-7: The running OMDb call count would exceed 500 (NFR-003 budget) — the system stops making OMDb calls, sets remaining candidates' IMDB fields to `None`/0, logs a WARNING, and proceeds with scoring.

**Postconditions**:
- Every candidate record has `imdb_rating` (float or `None`) and `imdb_vote_count` (int >= 0) attached.
- The execution log records total OMDb calls made and the enrichment success rate (e.g., "OMDb: 34 calls, 29 enriched, 5 not found").

**Acceptance Criteria**:
- AC-1: For a record with a valid IMDB ID and a valid OMDb entry, `imdb_rating` is a Python float between 1.0 and 10.0 (inclusive) and `imdb_vote_count` is a positive integer.
- AC-2: For a record where OMDb returns `"imdbRating": "N/A"`, `imdb_rating` is `None` (not the string `"N/A"`) and the pipeline does not raise an exception.
- AC-3: For a record with no TMDB `imdb_id`, no OMDb call is made, `imdb_rating` is `None`, and `imdb_vote_count` is 0.
- AC-4: `imdbVotes = "1,234,567"` is correctly parsed to the integer `1234567`.
- AC-5: The total number of OMDb API calls across a full run does not exceed 500, verifiable from the log entry.
- AC-6: No OMDb API key appears in any log file or PDF output.

---

### UC-010: Fetch India OTT Availability (TMDB Watch Providers, country=IN)

**ID**: UC-010
**Actor**: System
**Priority**: High
**Related FRs**: FR-009, FR-015, FR-016

**Preconditions**:
- UC-008 has produced the final list of at most 24 selected recommendation records.
- `TMDB_API_KEY` environment variable is set to a valid TMDB v3 API key.
- The permitted OTT platforms are statically configured: Netflix, Amazon Prime Video, Disney+ Hotstar, JioCinema, SonyLIV, Zee5.

**Main Flow**:
1. For each of the (at most 24) selected records, the system makes a GET request to the TMDB watch providers endpoint:
   - Movies: `https://api.themoviedb.org/3/movie/{id}/watch/providers?api_key={TMDB_API_KEY}`
   - TV Series: `https://api.themoviedb.org/3/tv/{id}/watch/providers?api_key={TMDB_API_KEY}`
2. The system extracts the `results.IN` object from the JSON response.
3. Within `results.IN`, the system checks the `flatrate` array (subscription streaming) for provider entries.
4. The system extracts `provider_name` from each entry in the `flatrate` array and checks whether it matches any of the 6 permitted platforms (case-insensitive partial match acceptable for variants like "Amazon Prime Video" vs "Prime Video").
5. The system stores the matched platform name(s) on the record as `ott_platforms` (a list of strings).
6. If `results.IN` is absent, or if `flatrate` is absent or empty, or if no matched provider is in the permitted list, the system sets `ott_platforms = []` and the display value becomes "Not confirmed on major OTT".
7. The system logs the number of titles for which at least one OTT platform was identified.

**Alternate Flows**:
- AF-1: TMDB watch providers call fails after 3 retries — the system sets `ott_platforms = []` for the affected title, logs the failure with the TMDB ID, and continues.
- AF-2: `results.IN` exists but only has `rent` or `buy` entries (no `flatrate`) — the system sets `ott_platforms = []` since the scope is subscription streaming only; the display shows "Not confirmed on major OTT".
- AF-3: The provider name returned by TMDB does not exactly match the permitted list due to a naming variant (e.g., "Prime Video" instead of "Amazon Prime Video") — the system normalizes common variants via a hardcoded alias map and maps them to the canonical name.

**Postconditions**:
- Every selected record has an `ott_platforms` attribute (list, possibly empty).
- The execution log records the count of titles with confirmed OTT availability.

**Acceptance Criteria**:
- AC-1: A title whose `results.IN.flatrate` contains `{"provider_name": "Netflix"}` has `ott_platforms = ["Netflix"]` stored on the record.
- AC-2: A title with no `results.IN` key in the TMDB watch providers response has `ott_platforms = []` and the PDF card displays "Platform: Not confirmed on major OTT".
- AC-3: A title available on both Netflix and SonyLIV has `ott_platforms = ["Netflix", "SonyLIV"]` (order determined by order of appearance in the TMDB response).
- AC-4: A title available on "Mubi" (not in the permitted list) has `ott_platforms = []` and the PDF card displays "Platform: Not confirmed on major OTT".
- AC-5: All 24 watch-provider API calls complete without the pipeline raising an unhandled exception, even if some calls return empty results.

---

### UC-011: Download Poster Thumbnail Images

**ID**: UC-011
**Actor**: System
**Priority**: Medium
**Related FRs**: FR-010, FR-015, FR-016, NFR-004

**Preconditions**:
- UC-008 has produced the final list of at most 24 selected records.
- Each record has a `poster_path` field from the TMDB response (may be `null`).
- A placeholder image file exists in the codebase at a known relative path (e.g., `assets/placeholder_poster.jpg`).
- The system has outbound HTTPS access to `image.tmdb.org`.

**Main Flow**:
1. For each of the (at most 24) selected records, the system checks whether `poster_path` is non-null and non-empty.
2. The system constructs the full poster URL: `https://image.tmdb.org/t/p/w342{poster_path}`.
3. The system makes a GET request to download the image bytes.
4. The system stores the image bytes in memory (or as a temp file) associated with the record for use by the PDF generator (UC-012).
5. If the download succeeds, the system attaches the image data to the record as `poster_image`.

**Alternate Flows**:
- AF-1: `poster_path` is `null` or empty — the system uses the placeholder image from the codebase and attaches it as `poster_image`; no HTTP request is made.
- AF-2: The HTTPS download fails after 3 retries (per UC-015) — the system uses the placeholder image, logs "Poster download failed for TMDB ID {id}, using placeholder", and continues.
- AF-3: The downloaded image is not a valid image file (cannot be opened by Pillow) — the system discards the downloaded bytes, uses the placeholder image, and logs the anomaly.
- AF-4: The cumulative size of all downloaded poster images would cause the in-memory footprint to exceed a reasonable threshold — the system processes images sequentially rather than concurrently, downloading and embedding each before moving to the next, to avoid memory exhaustion.

**Postconditions**:
- Every selected record has a `poster_image` value (either a downloaded w342 image or the placeholder image).
- No record proceeds to PDF generation without a valid `poster_image` attached.
- The execution log records the number of posters successfully downloaded and the number that fell back to the placeholder.

**Acceptance Criteria**:
- AC-1: For a record with a valid `poster_path`, the downloaded image is accessible as binary data and can be opened by Pillow without error.
- AC-2: For a record with `poster_path = null`, the placeholder image (not a blank/white rectangle) is used in the PDF, verifiable by visually inspecting the generated PDF.
- AC-3: If the poster download endpoint returns HTTP 404, the placeholder is used and no exception is propagated to the calling code.
- AC-4: The total size of all poster images embedded in the final PDF does not cause the PDF to exceed 10 MB (NFR-004).
- AC-5: The execution log contains a summary line such as "Posters: 21 downloaded, 3 using placeholder".

---

### UC-012: Generate PDF Report (Cover + Genre Cards)

**ID**: UC-012
**Actor**: System
**Priority**: Critical
**Related FRs**: FR-011, FR-012, FR-015, NFR-004, NFR-007

**Preconditions**:
- UC-008 has produced the final recommendation list (at most 24 records).
- UC-009 has attached IMDB rating and vote count to each record.
- UC-010 has attached OTT platform data to each record.
- UC-011 has attached poster image data to each record.
- Each record has `composite_score`, `tmdb_popularity`, `release_date` or `first_air_date`, `original_language`, and `overview` populated.
- `reportlab` or `fpdf2` library is installed and importable.

**Main Flow**:
1. The system instantiates the PDF generator and begins a new document.
2. The system renders a cover page containing: the report title ("Weekly Movie & Web Series Recommendations"), the generation date in the format "Saturday, DD Month YYYY", and a subtitle indicating the total number of recommendations and genres covered.
3. For each of the 4 genres (Action, Thriller, Drama, Comedy), in that canonical order, the system renders a genre section header page or section divider.
4. Within each genre section, the system first renders the Movies subsection (up to 3 cards), then the Web Series subsection (up to 3 cards).
5. For each recommendation, the system renders a card containing all of the following fields:
   - Poster thumbnail image (w342 size or placeholder)
   - Title (movie title or TV series name)
   - Release year (4-digit year extracted from `release_date` or `first_air_date`)
   - Language (human-readable: "Hindi", "English", "Kannada" derived from `original_language`)
   - Category label: "Movie" or "Web Series"
   - IMDB rating (displayed as "IMDB: 7.5/10" or "IMDB: N/A" if `imdb_rating` is `None`)
   - TMDB popularity score (displayed as "TMDB Popularity: 123.4")
   - OTT platform(s) (displayed as "Platform: Netflix, SonyLIV" or "Platform: Not confirmed on major OTT")
   - One-liner teaser: the `overview` field truncated to 120 characters; if `overview` exceeds 120 characters, it is cut at the last word boundary at or before character 120 and "..." is appended.
6. The system saves the completed PDF to the filesystem using the filename format `movie_recommendations_YYYY-MM-DD.pdf` where the date is the Saturday execution date.
7. The system logs the PDF filename, file size in KB, and total page count.

**Alternate Flows**:
- AF-1: A genre section has no qualifying titles for Movies but has qualifying titles for Web Series (or vice versa) — the system renders only the non-empty subsection; it does not render an empty subsection header.
- AF-2: A genre has no qualifying titles in either category — the system omits the entire genre section from the PDF (no section header, no empty cards).
- AF-3: The `overview` field is an empty string or null — the teaser is displayed as "No description available."
- AF-4: PDF generation fails due to a library error (e.g., corrupt image data causing a rendering exception) — the system logs the error with stack trace, attempts to fall back to the placeholder image for the affected card, and re-renders; if the second attempt also fails, the card is omitted and a warning is logged.
- AF-5: The generated PDF exceeds 10 MB — the system logs a WARNING with the actual file size and proceeds to email delivery; NFR-004 compliance is flagged for operator review.

**Postconditions**:
- A PDF file named `movie_recommendations_{YYYY-MM-DD}.pdf` exists on the filesystem.
- The PDF contains a cover page, at least one genre section, and cards for each selected title.
- The execution log records the PDF filename, file size in bytes, and page count.

**Acceptance Criteria**:
- AC-1: The generated PDF filename exactly matches `movie_recommendations_{execution_date}.pdf` where `{execution_date}` is the Saturday date in YYYY-MM-DD format.
- AC-2: The PDF cover page contains the generation date matching the Saturday execution date in the format "Saturday, DD Month YYYY" (e.g., "Saturday, 28 February 2026").
- AC-3: Every card in the PDF contains all 9 required fields: poster image, title, release year, language, category, IMDB rating, TMDB popularity, OTT platform, and teaser — verifiable by opening the PDF and inspecting 5 random cards.
- AC-4: A title with `overview = "This is a very long overview that exceeds the one hundred and twenty character limit set by the system for teaser display purposes in the weekly report."` is displayed in the PDF as a string of exactly 120 characters (or fewer if the last word boundary is before 120) followed by "...".
- AC-5: The generated PDF file size does not exceed 10 MB (10,485,760 bytes).
- AC-6: Running the pipeline twice on the same Saturday produces two PDF files with identical content (same titles, same scores, same order), satisfying NFR-007 (idempotency) — except for any upstream data changes.
- AC-7: A title with `imdb_rating = None` displays "IMDB: N/A" on its card (not "IMDB: None" or "IMDB: 0").

---

### UC-013: Email PDF to Recipient via Gmail SMTP

**ID**: UC-013
**Actor**: System
**Priority**: Critical
**Related FRs**: FR-013, FR-014, FR-015, FR-017, NFR-007

**Preconditions**:
- UC-012 has produced a PDF file at the expected filesystem path.
- `GMAIL_SENDER` environment variable is set to a valid Gmail address.
- `GMAIL_APP_PASSWORD` environment variable is set to a valid Gmail App Password (16-character Google app password, not the account password).
- `RECIPIENT_EMAIL` environment variable is set to the recipient's email address.
- PythonAnywhere free tier allows outbound SMTP connections to `smtp.gmail.com` on port 587 (per OQ-001 assumption).

**Main Flow**:
1. The system reads `GMAIL_SENDER`, `GMAIL_APP_PASSWORD`, and `RECIPIENT_EMAIL` from environment variables.
2. The system constructs a MIME multipart email message with:
   - `From`: the value of `GMAIL_SENDER`
   - `To`: the value of `RECIPIENT_EMAIL`
   - `Subject`: `Your Weekly Movie & Series Picks — {DD Month YYYY}` where the date is the Saturday execution date (e.g., "Your Weekly Movie & Series Picks — 28 February 2026")
   - Plain-text body: a brief summary stating the total number of recommendations (e.g., "22 titles recommended") and the genres covered (e.g., "Action, Thriller, Drama, Comedy")
   - PDF attachment: the file `movie_recommendations_{YYYY-MM-DD}.pdf` attached with MIME type `application/pdf`
3. The system opens a connection to `smtp.gmail.com` on port 587 using `STARTTLS`.
4. The system authenticates with the configured sender address and app password.
5. The system sends the email.
6. The system closes the SMTP connection.
7. The system logs "Email sent successfully to {RECIPIENT_EMAIL} at {timestamp}".

**Alternate Flows**:
- AF-1: SMTP authentication fails (wrong credentials) — the system logs a FATAL error with the SMTP error message (but not the password), closes the connection, and marks the run as failed in the log.
- AF-2: SMTP connection to `smtp.gmail.com:587` cannot be established (network error or port blocked) — the system logs a FATAL error with the socket error details and marks the run as failed.
- AF-3: The email is sent but delivery is rejected by Gmail (e.g., attachment too large) — the system logs the SMTP server error response and marks the run as failed.
- AF-4: The PDF file does not exist at the expected path (UC-012 failed to write it) — the system logs a FATAL error ("PDF file not found: {path}") and skips email delivery.
- AF-5: The pipeline has already sent an email for the current Saturday date (idempotency check per NFR-007) — the system detects the existence of a sentinel file or log entry indicating a successful send for this date and skips the SMTP call, logging "Email already sent for {date}, skipping duplicate send."

**Postconditions**:
- An email with the PDF attached has been delivered to the recipient's inbox (or the failure has been recorded in the log).
- The execution log contains either a success entry with timestamp or a FATAL failure entry with the error details.
- The SMTP connection is closed regardless of success or failure (no dangling connections).

**Acceptance Criteria**:
- AC-1: The email subject exactly matches the format `Your Weekly Movie & Series Picks — {DD Month YYYY}` where the day is spelled with leading zero if needed (e.g., "07 March 2026") and the month is the full English month name.
- AC-2: The email plain-text body contains the total recommendation count as an integer and lists all genres present in the report.
- AC-3: The email attachment filename is `movie_recommendations_{YYYY-MM-DD}.pdf` matching the execution date, and the attachment can be opened as a valid PDF.
- AC-4: The Gmail App Password does not appear in any log file, email header, or PDF content.
- AC-5: Running the pipeline twice on the same Saturday results in exactly one email delivered to the recipient (the second run detects the duplicate and skips sending), satisfying NFR-007.
- AC-6: If SMTP authentication fails, the pipeline exit code is non-zero and the execution log contains a FATAL-level entry with the SMTP error code.

---

### UC-014: Handle Sparse Kannada Content Gracefully

**ID**: UC-014
**Actor**: System
**Priority**: Medium
**Related FRs**: FR-003, FR-008, FR-011, FR-015

**Preconditions**:
- UC-004 has applied the language filter, resulting in a filtered list that may contain zero or very few Kannada-language (`kn`) titles.
- UC-008 has attempted to select top 3 per genre per category but some genre-category slots have fewer than 3 Kannada titles.

**Main Flow**:
1. After UC-008 completes selection, the system checks whether any genre-category slot has fewer than 3 titles.
2. The system specifically checks how many selected records have `original_language = 'kn'` across all genre-category slots.
3. If the total number of Kannada-language titles in the final recommendation list is 0, the system adds a note to the PDF (on the cover page or as a footer on relevant genre pages): "Note: No Kannada-language titles met the quality and recency criteria this week. Recommendations shown are in Hindi and/or English."
4. If Kannada titles are present but fewer than the maximum possible slots, the system does not add any scarcity note — partial representation is normal and expected.
5. If a specific genre-category slot has fewer than 3 titles (regardless of language), the system renders the available titles (0, 1, or 2) without padding and does not add placeholder empty cards.
6. The system logs the count of Kannada titles in the final recommendation list.

**Alternate Flows**:
- AF-1: Zero titles pass the language filter for Kannada across all genres — the system does not fail or warn at the filter stage (this is handled at the report generation stage as described in step 3 of the main flow).
- AF-2: A single Kannada title qualifies for the Drama genre under Movies but zero qualify for all other genre-category combinations — that single title is included normally in its slot; no scarcity note is added since at least one Kannada title is present.
- AF-3: The `spoken_languages` field contains `kn` for a title whose `original_language` is `hi` — that title passes the language filter via the spoken language check and is counted as a qualifying title; it does not count as a "Kannada-language title" for scarcity tracking (only `original_language = 'kn'` counts for scarcity reporting).

**Postconditions**:
- The PDF is generated without error regardless of Kannada content availability.
- If zero Kannada-original-language titles are in the final list, a scarcity note appears in the PDF.
- The execution log records the Kannada title count in the final selection.

**Acceptance Criteria**:
- AC-1: On a test run where no Kannada titles pass all filters, the pipeline still produces a PDF and sends an email (it does not abort or skip PDF generation).
- AC-2: On a test run where no Kannada titles are in the final selection, the PDF contains the exact scarcity note: "Note: No Kannada-language titles met the quality and recency criteria this week. Recommendations shown are in Hindi and/or English."
- AC-3: On a test run where at least one Kannada title (by `original_language`) is in the final selection, the scarcity note does not appear in the PDF.
- AC-4: A genre-category slot with 1 qualifying title renders exactly 1 card (not 3 cards with 2 blank/duplicate fillers).
- AC-5: The execution log contains a line such as "Kannada titles in final selection: 0" or "Kannada titles in final selection: 2" for every run.

---

### UC-015: Handle API Failures Gracefully (Retry with Exponential Backoff + Fallback + Logging)

**ID**: UC-015
**Actor**: System
**Priority**: High
**Related FRs**: FR-015, FR-016, FR-017, NFR-005

**Preconditions**:
- The pipeline is in progress and an outbound API call (to TMDB or OMDb) has returned a non-2xx HTTP status or has raised a network-level exception (timeout, connection refused, DNS failure).
- The retry mechanism is configured with: maximum 3 attempts, backoff delays of 1s (before attempt 2), 2s (before attempt 3), 4s (before declaring failure).

**Main Flow**:
1. The system makes the initial API call (attempt 1).
2. If the response is a 2xx HTTP status, the system processes the response normally and the retry mechanism is not invoked.
3. If the response is a retriable error (HTTP 429, 5xx, or a network exception), the system logs "Attempt 1 failed for {endpoint}: {error_detail}. Retrying in 1s."
4. The system waits 1 second, then makes attempt 2.
5. If attempt 2 fails, the system logs "Attempt 2 failed for {endpoint}: {error_detail}. Retrying in 2s."
6. The system waits 2 seconds, then makes attempt 3.
7. If attempt 3 fails, the system logs "Attempt 3 failed for {endpoint}: {error_detail}. Giving up."
8. The system applies the appropriate fallback behavior depending on the context:
   - For a TMDB trending endpoint failure (UC-002, UC-003): the system aborts the run with a FATAL log entry if zero records have been fetched, or continues with already-fetched records if partial data exists.
   - For a TMDB external IDs call failure (UC-009 step 1): the system skips OMDb enrichment for that title (sets `imdb_rating = None`, `imdb_vote_count = 0`) and continues.
   - For an OMDb call failure (UC-009 step 3): same fallback — `imdb_rating = None`, `imdb_vote_count = 0` — and continues.
   - For a TMDB watch providers call failure (UC-010): the system sets `ott_platforms = []` for that title and continues.
   - For a poster image download failure (UC-011): the system uses the placeholder image for that title and continues.
9. The system continues processing the remaining records in the pipeline.

**Alternate Flows**:
- AF-1: HTTP 401 (invalid API key) — this is a non-retriable error; the system does not retry but logs a FATAL entry with the HTTP status code and endpoint URL, then exits the pipeline immediately without retrying or continuing.
- AF-2: HTTP 400 (bad request) — treated as non-retriable; the system logs an ERROR for the affected record/call and applies the same fallback as a permanent failure (step 8) without retrying.
- AF-3: HTTP 404 (not found) on a per-record call (e.g., external IDs or watch providers for a specific ID) — treated as non-retriable; the system applies the per-record fallback immediately without retry attempts and logs the 404.
- AF-4: The system's internet connectivity is fully unavailable for all 3 retry attempts on the TMDB trending endpoint — the system logs a FATAL error and exits cleanly with a non-zero exit code.
- AF-5: An intermittent error causes attempt 1 and 2 to fail but attempt 3 to succeed — the system logs the two failures (with their retry delays) and then processes the successful response normally; the final log shows "Attempt 3 succeeded."

**Postconditions**:
- For every failed API call that exhausted all 3 retries, a log entry exists at ERROR or FATAL level with the endpoint URL, HTTP status code or exception type, and the string "Giving up."
- The pipeline continues running after per-record failures (TMDB external IDs, OMDb, watch providers, poster downloads) and exits only on FATAL failures (TMDB trending endpoint with zero records, invalid API key).
- Execution logs are retained for the most recent 8 runs; logs older than 8 runs are automatically deleted (NFR-005).

**Acceptance Criteria**:
- AC-1: When the TMDB trending endpoint returns HTTP 500 on attempts 1 and 2 but HTTP 200 on attempt 3, the pipeline proceeds normally and the log contains exactly two retry warning entries and one success entry for that endpoint call.
- AC-2: When the OMDb call for a specific IMDB ID fails all 3 retry attempts, the affected title has `imdb_rating = None` and `imdb_vote_count = 0` in the final recommendation data, and the pipeline continues to process all other titles.
- AC-3: When a TMDB call returns HTTP 401, the system does not make a second attempt (0 retries), logs a FATAL entry within the same execution, and exits with a non-zero process exit code.
- AC-4: The retry delays between attempts are at least 1 second (attempt 1 → 2), at least 2 seconds (attempt 2 → 3), and at least 4 seconds (wait period if attempt 3 also fails before giving up), verifiable by timestamping log entries.
- AC-5: The log directory contains at most 8 log files at any time; on the 9th run, the oldest log file is deleted before or after the new log is written, leaving exactly 8 files.
- AC-6: HTTP 404 responses on per-record calls (watch providers, external IDs) do not trigger any retry attempt; the fallback is applied immediately and a single ERROR log entry is written for that call.

---

## Appendix A: FR Coverage Matrix

| Use Case | FR-001 | FR-002 | FR-003 | FR-004 | FR-005 | FR-006 | FR-007 | FR-008 | FR-009 | FR-010 | FR-011 | FR-012 | FR-013 | FR-014 | FR-015 | FR-016 | FR-017 | FR-018 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| UC-001 | X | | | | | | | | | | | | | | X | | | |
| UC-002 | | X | | | | | | | | | | | | | X | X | X | |
| UC-003 | | X | | | | | | | | | | | | | X | X | X | |
| UC-004 | | | X | | | | | | | | | | | | X | | | |
| UC-005 | | | | X | | | | | | | | | | | X | | | X |
| UC-006 | | | | | X | | | | | | | | | | X | | | |
| UC-007 | | | | | | X | X | | | | | | | | X | | | |
| UC-008 | | | | | | | | X | | | | | | | X | | | X |
| UC-009 | | | | | | X | X | | | | | | | | X | X | X | |
| UC-010 | | | | | | | | | X | | | | | | X | X | | |
| UC-011 | | | | | | | | | | X | | | | | X | X | | |
| UC-012 | | | | | | | | | | | X | X | | | X | | | |
| UC-013 | | | | | | | | | | | | | X | X | X | | X | |
| UC-014 | | | X | | | | | X | | | X | | | | X | | | |
| UC-015 | | | | | | | | | | | | | | | X | X | | |

---

## Appendix B: Open Questions Affecting Use Cases

| OQ ID | Affects Use Cases | Resolution Assumed |
|---|---|---|
| OQ-001 | UC-013 | PythonAnywhere free tier allows outbound SMTP on port 587 to Gmail; must be verified during setup. |
| OQ-002 | UC-008 | "Up to 3" titles per slot — fewer than 3 is acceptable if insufficient titles qualify. |
| OQ-003 | UC-002, UC-003 | `/trending/week` combined with language and genre filters is sufficient for MVP; `/discover` fallback deferred to v1.1. |
| OQ-004 | UC-012 | Teaser is TMDB `overview` truncated to 120 characters — no LLM call in v1.0. |
| OQ-005 | UC-013 | Operator monitors execution logs; no automated alerting for expired Gmail App Password in v1.0. |
| OQ-006 | UC-003, UC-006 | Ongoing TV series are included provided `first_air_date` is within 365 days. |
| OQ-007 | UC-007 | No minimum vote count threshold for v1.0; the `log10` component naturally down-weights low-vote titles. |

---

## V2 Use Cases

---

### UC-016: Fetch Google Trends Score for India Per Title

**ID**: UC-016
**Actor**: System
**Priority**: High
**Related FRs**: FR-019, FR-022, FR-026

**Preconditions**:
- UC-018 has produced the pre-selected candidate pool (top 6 per genre per category by partial score).
- The `pytrends` library is installed and importable.
- The system has outbound HTTPS access to `trends.google.com`.

**Main Flow**:
1. The system iterates over each title in the pre-selected candidate pool produced by UC-018.
2. For each title, the system instantiates a `TrendReq` object with `hl='en-US'` and `tz=330` (IST offset).
3. The system calls `build_payload([title], geo='IN', timeframe='now 7-d')` using the title's display name.
4. The system calls `interest_over_time()` and reads the integer interest value from the returned DataFrame for the title keyword; the value represents the peak interest on a 0–100 scale for the past 7 days in India.
5. The system stores the retrieved integer as `trends_score` on the candidate record.
6. The system waits exactly 1.5 seconds before making the next pytrends request, regardless of whether the current request succeeded or failed.
7. The system logs the `trends_score` for each title in the format "Trends [IN]: {title} → {score}".

**Alternate Flows**:
- AF-1: `interest_over_time()` returns an empty DataFrame (pytrends returns no data for the title in the specified timeframe) — the system sets `trends_score = 0` for the affected title, logs "Trends [IN]: {title} → no data, defaulting to 0", and continues to the next title.
- AF-2: The pytrends call raises any exception (network error, `ResponseError`, `TooManyRequestsError`) — the system catches the exception, sets `trends_score = None` for the affected title (which is treated as 0 in the scoring formula), logs "Trends [IN]: {title} → FAILED ({exception_type}), defaulting to 0", and continues; the 1.5-second sleep is still applied before the next call.
- AF-3: The `pytrends` library is not installed or fails to import — the system logs a WARNING "pytrends not available; Google Trends enrichment skipped for all titles", sets `trends_score = None` for every candidate, and proceeds directly to scoring using a 0 contribution for the Trends signal.
- AF-4: The same title text produces a multi-keyword ambiguity (pytrends returns multiple columns) — the system reads only the column whose header exactly matches the queried title string; if no exact match exists, the system defaults to 0.

**Postconditions**:
- Every title in the pre-selected candidate pool has a `trends_score` value (integer 0–100 or `None` treated as 0).
- The total elapsed time for all pytrends calls is at least `(N - 1) * 1.5` seconds, where N is the number of titles in the pool, due to mandatory inter-request sleep.
- The execution log contains one Trends score entry per title.

**Acceptance Criteria**:
- AC-1: For a title where pytrends returns a DataFrame with a peak interest value of 72, `trends_score` is stored as the integer `72` (not a float, not a string).
- AC-2: For a title where pytrends returns an empty DataFrame, `trends_score` is `0` and the pipeline does not raise an exception.
- AC-3: For a title where pytrends raises a `TooManyRequestsError`, `trends_score` is `0`, the exception is caught and logged at WARNING level, and the pipeline continues to process the next title without aborting.
- AC-4: When processing a pool of N titles, the total number of inter-request sleep intervals is exactly N - 1, and each interval is at least 1.5 seconds, verifiable from log timestamps.
- AC-5: No Google Trends call is made for any title that was not included in the pre-selected candidate pool produced by UC-018; titles excluded at the pre-selection stage have `trends_score = None`.

---

### UC-017: Fetch YouTube Trailer View Count Per Title

**ID**: UC-017
**Actor**: System
**Priority**: High
**Related FRs**: FR-020, FR-022, FR-023, FR-025

**Preconditions**:
- UC-018 has produced the pre-selected candidate pool (top 6 per genre per category by partial score).
- `YOUTUBE_API_KEY` environment variable is set to a valid YouTube Data API v3 key.
- The system has outbound HTTPS access to `www.googleapis.com`.

**Main Flow**:
1. The system reads `YOUTUBE_API_KEY` from the environment.
2. For each title in the pre-selected candidate pool, the system extracts the display name and the 4-digit release year from the record's `release_date` or `first_air_date`.
3. The system constructs a YouTube Data API v3 `search.list` request with: `q="{title} {year} official trailer"`, `part=snippet`, `maxResults=1`, `type=video`, `key={YOUTUBE_API_KEY}`.
4. The system sends the `search.list` request and extracts the `videoId` from the first item in the `items` array of the response.
5. The system constructs a `videos.list` request with: `id={videoId}`, `part=statistics`, `key={YOUTUBE_API_KEY}`.
6. The system sends the `videos.list` request and extracts `viewCount` from `items[0].statistics.viewCount`, converting it from a string to an integer.
7. The system stores the integer as `yt_views` on the candidate record.
8. The system logs "YouTube: {title} → {yt_views} views (video ID: {videoId})".

**Alternate Flows**:
- AF-1: The `search.list` response returns an empty `items` array (no matching video found) — the system sets `yt_views = None` (treated as 0 in scoring) for the affected title, logs "YouTube: {title} → no trailer found, defaulting to 0", and continues.
- AF-2: The `videos.list` response returns an empty `items` array (video ID no longer valid) — the system sets `yt_views = None`, logs "YouTube: {title} → video not found for ID {videoId}, defaulting to 0", and continues.
- AF-3: Either the `search.list` or `videos.list` request returns HTTP 403 with `quotaExceeded` error — the system catches the error, sets `yt_views = None` for the current title and all remaining titles in the pool (to avoid further quota consumption), logs a WARNING "YouTube API quota exceeded; YouTube enrichment disabled for remaining titles", and continues the pipeline with the 0 contribution for YouTube signal on all affected titles.
- AF-4: Either API call raises a network-level exception (timeout, connection error) — the system sets `yt_views = None` for the affected title, logs the exception at WARNING level, and continues to the next title.
- AF-5: The `viewCount` field is absent from `statistics` (e.g., views are hidden by the channel) — the system sets `yt_views = None` (treated as 0), logs "YouTube: {title} → viewCount unavailable, defaulting to 0".

**Postconditions**:
- Every title in the pre-selected candidate pool has a `yt_views` value (positive integer or `None` treated as 0 in scoring).
- Total YouTube Data API v3 units consumed for the run does not exceed 5,000 (each `search.list` costs 100 units; each `videos.list` costs 1 unit; maximum pool size of 48 titles yields at most 4,848 units).
- The execution log contains one YouTube view count entry per title processed.

**Acceptance Criteria**:
- AC-1: For a title where `search.list` returns a video ID and `videos.list` returns `viewCount = "3500000"`, `yt_views` is stored as the integer `3500000`.
- AC-2: For a title where `search.list` returns an empty `items` array, `yt_views` is `None`, the pipeline does not raise an exception, and the log contains "no trailer found" for that title.
- AC-3: When the API returns HTTP 403 with `quotaExceeded`, all subsequent titles in the pool have `yt_views = None` without making any additional YouTube API calls; a single WARNING log entry records the quota exhaustion event.
- AC-4: The total YouTube Data API unit cost across the entire run does not exceed 5,000 units, computed as `(search.list calls * 100) + (videos.list calls * 1)`, verifiable from the log entry "YouTube API units consumed: {total}".
- AC-5: No YouTube API call is made for any title not in the pre-selected candidate pool produced by UC-018.

---

### UC-018: Pre-Select Candidate Pool Before Enrichment

**ID**: UC-018
**Actor**: System
**Priority**: Medium
**Related FRs**: FR-022

**Preconditions**:
- UC-006 has produced recency-filtered lists of movies and TV series candidates (all titles that passed language, genre, and recency filters).
- UC-009 has completed OMDb enrichment for all recency-filtered candidates, attaching `imdb_rating`, `imdb_vote_count`, and `tmdb_popularity` to each record.
- The constants `TOP_N = 3` and `PRE_SELECT_MULTIPLIER = 2` are statically configured, making the pre-selection pool size `TOP_N * PRE_SELECT_MULTIPLIER = 6` per genre per category.

**Main Flow**:
1. The system groups the recency-filtered and OMDb-enriched candidates by genre and category (Movies, Web Series), mirroring the same genre-category bucketing used in UC-007 and UC-008.
2. For each genre-category bucket, the system computes a partial composite score using only the three V1 signals: `partial_score = (tmdb_popularity * 0.4) + (imdb_rating * 10 * 0.4) + (log10(imdb_vote_count + 1) * 0.2)`. Titles with `imdb_rating = None` receive 0 for that component, identical to V1 behaviour.
3. The system ranks all candidates within each bucket by `partial_score` descending.
4. The system selects the top `min(6, N)` candidates from each bucket, where N is the total number of candidates in that bucket, forming the pre-selected pool.
5. The system passes the pre-selected pool (at most 6 titles per genre per category, at most 48 titles total) to UC-016 and UC-017 for V2 enrichment.
6. The system logs for each genre-category bucket: the total candidate count, the pre-selected count, and the `partial_score` of the highest- and lowest-ranked candidate in the pool.

**Alternate Flows**:
- AF-1: A genre-category bucket contains fewer than 6 candidates — the system selects all available candidates for that bucket without padding, logs "Pre-select: {genre} {category} — {N} of {N} available (pool < 6)", and passes all N to enrichment.
- AF-2: A genre-category bucket contains 0 candidates — the system logs "Pre-select: {genre} {category} — 0 candidates, skipping enrichment for this bucket" and passes an empty list to UC-016 and UC-017 for that bucket; no enrichment calls are made for that bucket.
- AF-3: Two candidates share the same `partial_score` at the boundary of the top-6 cut (e.g., both are ranked 6th) — the system uses `tmdb_popularity` as the tiebreaker (higher popularity is included in the pool); if still equal, the alphabetically earlier title is included.

**Postconditions**:
- A pre-selected candidate pool exists in memory containing at most 6 titles per genre per category (at most 48 titles total across 4 genres x 2 categories).
- Every title in the pool has a computed `partial_score` value.
- UC-016 and UC-017 receive only the pre-selected pool; no title outside the pool undergoes Google Trends or YouTube enrichment.
- The execution log contains a pre-selection summary for each genre-category bucket.

**Acceptance Criteria**:
- AC-1: Given a genre-category bucket with 10 candidates, exactly 6 are selected for the pool — the 6 with the highest `partial_score` — and the remaining 4 do not receive any Google Trends or YouTube API calls.
- AC-2: Given a genre-category bucket with 4 candidates, exactly 4 are selected (no padding to 6), and the log entry for that bucket reads "Pre-select: {genre} {category} — 4 of 4 available (pool < 6)".
- AC-3: The `partial_score` formula used in pre-selection is identical to the V1 composite score formula (same weights: 0.4 / 0.4 / 0.2), verifiable by unit test comparing pre-selection scores to V1 composite scores for the same input values.
- AC-4: When two candidates tie at the 6th position by `partial_score`, the one with the higher `tmdb_popularity` is included in the pool and the other is excluded; both cases are reflected in the log.
- AC-5: The maximum number of titles entering UC-016 (Google Trends) and UC-017 (YouTube) across the entire run is 48 (4 genres x 2 categories x 6 titles); no run exceeds this limit.

---

### UC-019: Display Trends Score and YouTube Views in PDF

**ID**: UC-019
**Actor**: System
**Priority**: Medium
**Related FRs**: FR-024

**Preconditions**:
- UC-016 has attached `trends_score` (integer 0–100 or `None`) to each selected title in the final recommendation list.
- UC-017 has attached `yt_views` (positive integer or `None`) to each selected title.
- UC-012's PDF generation is in progress; content card rendering is about to begin for each title.

**Main Flow**:
1. For each title in the final recommendation list, the system begins rendering its PDF content card.
2. If `trends_score` is a non-None integer (including 0), the system renders the label "Trending: {trends_score}/100" on the card, where `{trends_score}` is the integer value with no decimal places.
3. If `yt_views` is a non-None positive integer, the system formats the view count for display: values >= 1,000,000 are formatted as `{X.X}M views` (rounded to 1 decimal place); values >= 1,000 but < 1,000,000 are formatted as `{X.X}K views`; values < 1,000 are displayed as the raw integer followed by " views". The system renders the label "Trailer: {formatted_views}" on the card.
4. If `trends_score` is `None`, the "Trending" field is omitted from the card entirely; no placeholder, dash, or "N/A" is rendered for that field.
5. If `yt_views` is `None` or 0, the "Trailer" field is omitted from the card entirely; no placeholder, dash, or "N/A" is rendered for that field.
6. The system continues rendering all remaining card fields (poster, title, IMDB rating, OTT platform, etc.) regardless of whether the V2 fields are present or absent.

**Alternate Flows**:
- AF-1: A title was not included in the pre-selected candidate pool (UC-018) and therefore has neither `trends_score` nor `yt_views` attributes on its record — the system treats both as `None` and omits both fields from the card silently, with no exception raised.
- AF-2: `yt_views` is exactly `0` (a title with zero views, which can happen if a trailer exists but has no recorded views) — the system treats this as equivalent to `None` and omits the "Trailer" field from the card.
- AF-3: `trends_score` is exactly `0` (a title with measurably zero search interest in India this week) — unlike `yt_views`, a `trends_score` of `0` is a valid data point and IS rendered as "Trending: 0/100" on the card (not omitted).

**Postconditions**:
- Every card in the PDF renders "Trending: N/100" if and only if the title's `trends_score` is a non-None integer.
- Every card in the PDF renders "Trailer: X.XM views" (or equivalent K/raw format) if and only if the title's `yt_views` is a non-None integer greater than 0.
- No card contains the text "None", "N/A", "0 views", or a blank label for Trends or YouTube where data is absent — those fields are simply omitted.

**Acceptance Criteria**:
- AC-1: A card for a title with `trends_score = 85` and `yt_views = 3500000` displays exactly "Trending: 85/100" and "Trailer: 3.5M views" on the rendered card, verifiable by inspecting the PDF.
- AC-2: A card for a title with `trends_score = 0` displays "Trending: 0/100" (not omitted), confirming that a zero Trends score is treated as present data.
- AC-3: A card for a title with `yt_views = None` does not contain the text "Trailer" anywhere on that card in the PDF.
- AC-4: A card for a title with `yt_views = 750000` displays "Trailer: 750.0K views" (K format, not M format).
- AC-5: A card for a title with `trends_score = None` and `yt_views = None` renders all 9 existing V1 card fields without raising an exception and without any visible gap or broken layout where the V2 fields would have appeared.

---

### UC-020: Gracefully Degrade When Trends or YouTube Unavailable

**ID**: UC-020
**Actor**: System
**Priority**: High
**Related FRs**: FR-019, FR-020, FR-025, NFR-009

**Preconditions**:
- The pipeline has reached the enrichment stage (UC-016 and/or UC-017) and one or both of the following conditions is true:
  - pytrends is unavailable, has raised an unrecoverable error, or has been skipped due to repeated failures.
  - `YOUTUBE_API_KEY` is absent or empty, or the YouTube API has returned a quota-exceeded or authentication error.
- UC-009 (OMDb enrichment) has already completed successfully, providing `imdb_rating`, `imdb_vote_count`, and `tmdb_popularity` on all candidate records.

**Main Flow**:
1. The system checks `trends_score` for each title at scoring time (UC-007 equivalent for V2).
2. If `trends_score` is `None` for a title (pytrends failed or was skipped), the Trends signal contribution is set to `0.0` in the 5-signal formula for that title: `(trends_score / 100) * 0.10` evaluates to `0.0`.
3. The system checks `yt_views` for each title at scoring time.
4. If `yt_views` is `None` for a title (YouTube enrichment failed or was skipped), the YouTube signal contribution is set to `0.0` in the 5-signal formula for that title: `(min(yt_views, 10_000_000) / 10_000_000) * 0.10` evaluates to `0.0`.
5. If `YOUTUBE_API_KEY` is absent or empty at startup, the system logs exactly one WARNING entry: "YOUTUBE_API_KEY not set; YouTube enrichment skipped. Score contribution will be 0 for all titles." No per-title warnings are emitted for missing YouTube data in this case.
6. If both `trends_score` and `yt_views` are `None` for all titles (total V2 failure), the effective scoring formula collapses to: `score = (imdb_rating / 10) * 0.45 + (min(popularity, 200) / 200) * 0.20 + (min(votes, 5000) / 5000) * 0.15`, which is functionally equivalent to a 3-signal V1-style ranking (though with updated weights, not the original V1 weights).
7. The pipeline continues to produce a PDF and send an email using the degraded scores; no run is aborted solely because V2 enrichment data is unavailable.
8. The system logs a summary at the end of the scoring step: "Scoring: trends available for {M} of {N} titles; YouTube available for {P} of {N} titles."

**Alternate Flows**:
- AF-1: pytrends succeeds for some titles but fails for others — the system uses the actual `trends_score` for titles where it succeeded and `0.0` contribution for titles where it failed; no special handling beyond what is described in the main flow is required.
- AF-2: YouTube succeeds for some titles but quota is exhausted partway through the pool — the system uses actual `yt_views` for titles already enriched and `0.0` for remaining titles; the quota exhaustion WARNING is logged once when it occurs (per UC-017 AF-3).
- AF-3: Both pytrends and YouTube fail on the same run and `YOUTUBE_API_KEY` is set — the system emits two separate WARNING log entries (one for pytrends failure, one for YouTube failure) and continues; the final report is generated using only the 3 available signals at their respective weights.

**Postconditions**:
- The pipeline produces a valid PDF report and sends an email regardless of the availability of Google Trends and YouTube enrichment data.
- The final composite score for every title is a non-negative float computed from whatever signals are available (1 to 5 signals), with missing signals contributing 0.
- The execution log contains the scoring summary line reporting how many titles received Trends and YouTube data.

**Acceptance Criteria**:
- AC-1: When pytrends raises an exception for every title in the pool, all titles have `trends_score = None`, the Trends signal contributes exactly `0.0` to every title's composite score, the pipeline does not abort, and a PDF and email are produced for that run.
- AC-2: When `YOUTUBE_API_KEY` is not set in the environment, the pipeline emits exactly one WARNING log entry containing "YOUTUBE_API_KEY not set", makes zero YouTube API calls, and assigns `yt_views = None` to all titles without any per-title WARNING entries.
- AC-3: When both pytrends and YouTube are completely unavailable, the composite scores computed for all titles are mathematically equivalent to applying the V2 5-signal formula with `trends_score = 0` and `yt_views = 0` for all titles; the ranking order of titles must be deterministic and reproducible for the same input IMDB/TMDB data.
- AC-4: The execution log's scoring summary line matches the format "Scoring: trends available for {M} of {N} titles; YouTube available for {P} of {N} titles" where M, P, and N are non-negative integers and M <= N and P <= N.
- AC-5: A run in which only pytrends fails (YouTube succeeds for all titles) still uses actual `yt_views` values in scoring for all titles that received YouTube data; the YouTube signal is NOT zeroed out due to pytrends failure — each signal degrades independently.
