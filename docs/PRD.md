# PRD: Weekly Movie & Web Series Recommender

**Version:** 1.0
**Date:** 2026-03-01
**Status:** Draft

---

## 1. Problem Statement

Discovering new movies and web series worth watching across fragmented OTT platforms is time-consuming. Manually tracking new releases in preferred languages and genres requires checking multiple apps and review sites weekly. This service automates that discovery, curates the best content using objective scoring, and delivers a ready-to-use recommendation report every Saturday morning.

---

## 2. Goals

- Deliver a curated, scored PDF report of top movies and web series every Saturday without manual effort.
- Surface only content released within the last 365 days across Hindi, English, and Kannada languages.
- Rank content using a composite score of TMDB popularity, IMDB rating, and vote count.
- Cover all major Indian OTT platforms so the recipient knows exactly where to watch.
- Operate entirely within free-tier API and hosting constraints.

---

## 3. Non-Goals

- No user-facing UI, web dashboard, or mobile app.
- No support for languages beyond Hindi, English, and Kannada.
- No support for genres beyond Action, Thriller, Drama, and Comedy.
- No real-time or on-demand recommendations; the schedule is fixed to weekly Saturday runs.
- No user authentication, personalization based on watch history, or feedback loops.
- No paid API tiers, paid hosting, or paid email services.
- No SMS, push notification, or WhatsApp delivery; email only.
- No content download, streaming links, or DRM handling.

---

## 4. Target Users

| Role | Description |
|---|---|
| **System Operator** | The person who sets up, hosts, and maintains the service on PythonAnywhere (Ketan). |
| **Report Recipient** | The person who receives and reads the weekly PDF email (Ketan's wife). |

The recipient requires no technical knowledge. The email and PDF must be self-explanatory without any supporting instructions.

---

## 5. User Stories

**US-001** — As the report recipient, I want to receive a PDF email every Saturday morning so that I can plan my weekend watching without searching multiple apps.

**US-002** — As the report recipient, I want to see movie poster thumbnails in the report so that I can visually identify content at a glance.

**US-003** — As the report recipient, I want a one-liner teaser for each recommended title so that I can quickly decide if the plot interests me.

**US-004** — As the report recipient, I want to know which OTT platform streams each title so that I do not have to search for it separately.

**US-005** — As the report recipient, I want content filtered to Hindi, English, and Kannada only so that I do not receive irrelevant regional recommendations.

**US-006** — As the report recipient, I want recommendations grouped by genre so that I can pick content matching my current mood.

**US-007** — As the operator, I want the service to run automatically every Saturday without any manual trigger so that I do not have to remember to run it.

**US-008** — As the operator, I want all external API calls handled within free-tier rate limits so that the service incurs zero cost to run.

**US-009** — As the operator, I want execution logs retained so that I can diagnose failures without accessing the live process.

**US-010** — As the report recipient, I want to see the IMDB rating alongside each recommendation so that I can gauge quality before committing watch time.

---

## 6. Functional Requirements

**FR-001** — The system shall execute automatically every Saturday between 07:00 and 09:00 IST using PythonAnywhere's scheduled task feature.

**FR-002** — The system shall fetch trending movies from the TMDB `/trending/movie/week` endpoint and trending TV series from the TMDB `/trending/tv/week` endpoint.

**FR-003** — The system shall filter fetched content to include only titles whose original language or spoken language list includes at least one of: `hi` (Hindi), `en` (English), `kn` (Kannada).

**FR-004** — The system shall filter fetched content to include only titles whose genre list intersects with: Action (id: 28/10759), Thriller (id: 53), Drama (id: 18), Comedy (id: 35).

**FR-005** — The system shall exclude any title whose release date (for movies: `release_date`; for TV: `first_air_date`) is more than 365 days before the execution date.

**FR-006** — The system shall query the OMDb API using each title's IMDB ID (obtained via TMDB's `/movie/{id}/external_ids` or `/tv/{id}/external_ids`) to retrieve the IMDB rating and vote count.

**FR-007** — The system shall compute a composite score for each title using the formula:
`Score = (TMDB_popularity * 0.4) + (IMDB_rating * 10 * 0.4) + (log10(IMDB_vote_count + 1) * 0.2)`
Titles with no IMDB rating shall receive an IMDB component score of 0.

**FR-008** — The system shall select the top 3 highest-scoring titles per genre per category (Movies and Web Series separately), producing a maximum of 24 recommendations per report (4 genres x 3 titles x 2 categories).

**FR-009** — The system shall query TMDB's `/movie/{id}/watch/providers` or `/tv/{id}/watch/providers` for the `IN` region and map results to the following platform list: Netflix, Amazon Prime Video, Disney+ Hotstar, JioCinema, SonyLIV, Zee5. Titles with no matching platform shall display "Platform: Not confirmed on major OTT".

**FR-010** — The system shall download the TMDB poster image for each selected title at the `w342` size. If a poster is unavailable, the system shall use a placeholder image embedded in the codebase.

**FR-011** — The system shall generate a single PDF report containing: report title, generation date, one section per genre, and within each section one card per title displaying — poster thumbnail, title, release year, language, category (Movie/Web Series), IMDB rating, TMDB popularity score, OTT platform(s), and a one-liner teaser derived from the TMDB overview field (truncated to 120 characters with ellipsis if needed).

**FR-012** — The system shall name the generated PDF file using the format `movie_recommendations_YYYY-MM-DD.pdf` where the date is the Saturday execution date.

**FR-013** — The system shall send the PDF as an email attachment via Gmail SMTP (port 587, STARTTLS) from a configured sender address to a configured recipient address.

**FR-014** — The email subject shall follow the format: `Your Weekly Movie & Series Picks — <DD Month YYYY>` and the email body shall contain a brief plain-text summary listing the total number of recommendations and the genres covered.

**FR-015** — The system shall write a structured execution log for each run recording: start time, number of titles fetched, number passing each filter stage, any API errors with HTTP status codes, and completion status (success/failure).

**FR-016** — The system shall handle TMDB or OMDb API failures gracefully: if an API call fails after 3 retries with exponential backoff (1s, 2s, 4s), the system shall skip the affected title and continue processing remaining titles rather than aborting the run.

**FR-017** — The system shall read all credentials (TMDB API key, OMDb API key, Gmail sender address, Gmail app password, recipient email address) exclusively from environment variables or a `.env` file; no credentials shall be hardcoded in source files.

**FR-018** — The system shall deduplicate titles across genres: if the same title qualifies under multiple genres, it shall appear only under the genre in which it achieved its highest composite score.

---

## 7. Non-Functional Requirements

**NFR-001** — The end-to-end execution (fetch, score, generate PDF, send email) shall complete within 10 minutes on PythonAnywhere's free CPU tier.

**NFR-002** — Total TMDB API calls per run shall not exceed 500 requests, staying within the free-tier limit of 1,000 requests per day.

**NFR-003** — Total OMDb API calls per run shall not exceed 500 requests, staying within the free-tier limit of 1,000 requests per day.

**NFR-004** — The generated PDF file size shall not exceed 10 MB to ensure reliable email delivery via Gmail (25 MB attachment limit provides headroom).

**NFR-005** — The system shall retain execution logs for the most recent 8 runs (8 weeks) and automatically delete older log files to manage free-tier disk quota.

**NFR-006** — The codebase shall run on Python 3.10+ without requiring any dependencies outside of: `requests`, `reportlab` (or `fpdf2`), `Pillow`, and `python-dotenv`.

**NFR-007** — The system shall be idempotent: running it twice on the same Saturday shall produce a report with identical content (assuming no upstream data changes) and shall not send duplicate emails.

---

## 8. Constraints

| Constraint | Detail |
|---|---|
| **Hosting** | PythonAnywhere free tier only. No persistent background processes; scheduled tasks only. |
| **TMDB API** | Free tier. Authentication via API key (v3 auth). No premium endpoints. |
| **OMDb API** | Free tier. 1,000 requests/day limit. |
| **Email** | Gmail SMTP with App Password. No SendGrid, SES, or paid relay. |
| **Languages** | Strictly `hi`, `en`, `kn`. No additions without a code change and redeployment. |
| **Genres** | Strictly Action, Thriller, Drama, Comedy. No additions without a code change. |
| **OTT Scope** | Netflix, Amazon Prime Video, Disney+ Hotstar, JioCinema, SonyLIV, Zee5. India region only. |
| **Content Age** | No title older than 365 days from execution date shall appear in the report. |
| **Cost** | Total monthly operating cost must be USD 0. |

---

## 9. Success Metrics

| Metric | Target |
|---|---|
| **Delivery reliability** | Email received by recipient on >= 90% of Saturdays over any 8-week rolling window. |
| **Report completeness** | Each PDF contains >= 18 recommendations (75% fill rate of the 24-slot maximum). |
| **Execution time** | Run completes within 10 minutes on >= 95% of executions. |
| **Zero cost** | Monthly API + hosting cost = USD 0.00 for 12 consecutive months. |
| **No duplicates** | The same title does not appear in two consecutive weekly reports. |
| **Filter accuracy** | 100% of recommended titles match at least one configured language and one configured genre, verifiable by spot-checking 3 random titles per report. |

---

## 10. Open Questions

| ID | Question | Assumption Made |
|---|---|---|
| OQ-001 | Does PythonAnywhere free tier allow outbound SMTP on port 587? | Assumed yes; must be verified during setup. PythonAnywhere free tier is known to whitelist Gmail SMTP. |
| OQ-002 | Should the top-3 per genre be strictly 3, or "up to 3" if fewer qualify? | Assumed "up to 3" — the report is generated with however many titles pass all filters for that slot. |
| OQ-003 | TMDB trending endpoint returns global trends. Is that sufficient for India-relevant content, or should `/trending` be combined with a region-filtered discover call? | Assumed `/trending/week` combined with language and genre filters is sufficient for an MVP. A `/discover` fallback can be added in v1.1 if coverage is insufficient. |
| OQ-004 | How is the one-liner teaser generated — TMDB overview truncation or an LLM call? | Assumed TMDB overview truncated to 120 characters. No LLM dependency in v1.0. |
| OQ-005 | What happens if Gmail App Password expires or is revoked? | Assumed the operator monitors the execution log and reconfigures the credential. No automated alerting in v1.0. |
| OQ-006 | Should Web Series include both completed and ongoing series? | Assumed yes, provided the `first_air_date` is within the last 365 days. |
| OQ-007 | Is the IMDB vote count threshold required to prevent low-sample titles from ranking high? | Assumed no minimum vote count for v1.0. The composite score formula naturally down-weights titles with low vote counts via the log10 component. |

---

## V2 Additions — Google Trends & YouTube Enrichment

### V2 Problem Statement
V1 scoring relies solely on IMDB ratings and TMDB popularity. These signals are global and
do not capture real-time Indian audience interest. V2 adds two India-specific signals to
surface content that is genuinely trending in India right now.

### V2 Goals
- Add India-specific search buzz signal (Google Trends, geo=IN)
- Add genuine audience engagement signal (YouTube trailer views)
- Keep all V2 enrichment within free API tiers
- Gracefully degrade to V1 behaviour when new APIs are unavailable

### V2 Functional Requirements

**FR-019** — The system shall query Google Trends (pytrends) for each candidate title using
geo=IN and timeframe="now 7-d", returning an interest score (0–100). If pytrends fails for
any title, that title's Trends score shall default to 0 without aborting the pipeline.

**FR-020** — The system shall query YouTube Data API v3 for each candidate title's official
trailer using search.list (query: "{title} {year} official trailer", maxResults=1), then
fetch viewCount via videos.list. If the YouTube API fails or returns no results, that title's
view count shall default to 0 without aborting the pipeline.

**FR-021** — The composite scoring formula shall be updated to 5 signals:
score = (imdb_rating/10)*0.45 + (min(popularity,200)/200)*0.20 + (min(votes,5000)/5000)*0.15
      + (trends_score/100)*0.10 + (min(yt_views,10_000_000)/10_000_000)*0.10

**FR-022** — Google Trends and YouTube enrichment shall run only on a pre-selected candidate
pool of top-6 items per genre (PRE_SELECT_MULTIPLIER=2 × TOP_N=3), not on all fetched items,
to conserve API quota.

**FR-023** — Total YouTube Data API v3 usage per run shall not exceed 5,000 units
(well within the 10,000 units/day free quota).

**FR-024** — The PDF report shall display the Google Trends score ("Trending: N/100") and
YouTube trailer views ("Trailer: X.XM views") on each content card where data is available.
If data is unavailable for a title, those fields shall be omitted from that card.

**FR-025** — The system shall accept YOUTUBE_API_KEY as an optional environment variable.
If absent or empty, YouTube enrichment shall be skipped with a WARNING log message, and
score contribution from YouTube shall be 0 for all titles.

**FR-026** — Google Trends requests shall be spaced at least 1.5 seconds apart to avoid
triggering Google rate-limiting on the unofficial pytrends endpoint.

### V2 Non-Functional Requirements

**NFR-008** — V2 enrichment (Google Trends + YouTube) shall add no more than 3 minutes to
total pipeline execution time (at 1.5s/title × 48 titles = ~72s for Trends; YouTube is async).

**NFR-009** — V2 shall remain fully functional as V1 (no Trends/YouTube data) if both new
APIs fail simultaneously. Rankings shall fall back to the 3-signal V1 formula automatically.
