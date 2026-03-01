"""
Configuration module for the Weekly Movie & Web Series Recommender.

Loads all settings from environment variables (via python-dotenv) and
exposes typed constants used throughout the pipeline.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List

from dotenv import load_dotenv

# Load .env file if present (no-op on PythonAnywhere where env vars are set directly)
load_dotenv()

# ---------------------------------------------------------------------------
# Scoring / filter constants
# ---------------------------------------------------------------------------

TOP_N: int = 3
RECENCY_DAYS: int = 365
MIN_VOTE_COUNT: int = 50

# ---------------------------------------------------------------------------
# Genre IDs (TMDB)
# Movie-specific: Action=28, Thriller=53, Drama=18, Comedy=35
# TV-specific:    Action & Adventure=10759, Mystery=9648, Drama=18, Comedy=35
# ---------------------------------------------------------------------------

GENRE_IDS: Dict[str, List[int]] = {
    "Action":  [28, 10759],
    "Thriller": [53, 9648],
    "Drama":   [18],
    "Comedy":  [35],
}

# Flat set of all permitted genre IDs for quick membership tests
ALL_PERMITTED_GENRE_IDS: set = {gid for ids in GENRE_IDS.values() for gid in ids}

# Map from TMDB genre ID -> canonical genre name
GENRE_ID_TO_NAME: Dict[int, str] = {
    28:    "Action",
    10759: "Action",
    53:    "Thriller",
    9648:  "Thriller",
    18:    "Drama",
    35:    "Comedy",
}

# Canonical genre display order in the report
GENRE_ORDER: List[str] = ["Action", "Thriller", "Drama", "Comedy"]

# ---------------------------------------------------------------------------
# Language codes
# ---------------------------------------------------------------------------

LANGUAGE_CODES: Dict[str, str] = {
    "hi": "Hindi",
    "en": "English",
    "kn": "Kannada",
    "ta": "Tamil",
    "te": "Telugu",
    "ml": "Malayalam",
}

# All languages whose original-language content is included directly
SUPPORTED_LANGUAGES: List[str] = list(LANGUAGE_CODES.keys())

# South Indian languages (subset of SUPPORTED_LANGUAGES)
SOUTH_INDIAN_LANGUAGES: List[str] = ["kn", "ta", "te", "ml"]

# Content in any other language passes the filter if dubbed in one of these
DUB_LANGUAGES: List[str] = ["hi", "en", "kn"]

# ---------------------------------------------------------------------------
# OTT provider ID mapping for India (TMDB provider IDs)
# ---------------------------------------------------------------------------

OTT_PROVIDER_IDS: Dict[int, str] = {
    8:   "Netflix",
    119: "Amazon Prime Video",
    122: "Disney+ Hotstar",
    220: "JioCinema",
    237: "SonyLIV",
    232: "Zee5",
}

# Alias map: normalises TMDB provider_name strings to canonical names
OTT_NAME_ALIASES: Dict[str, str] = {
    "netflix":              "Netflix",
    "amazon prime video":   "Amazon Prime Video",
    "prime video":          "Amazon Prime Video",
    "amazon prime":         "Amazon Prime Video",
    "disney+ hotstar":      "Disney+ Hotstar",
    "hotstar":              "Disney+ Hotstar",
    "jiocinetma":           "JioCinema",
    "jio cinema":           "JioCinema",
    "jiociema":             "JioCinema",
    "jiocinam":             "JioCinema",
    "jiocinam":             "JioCinema",
    "jiocinem":             "JioCinema",
    "jiocin":               "JioCinema",
    "jiocinema":            "JioCinema",
    "sonyliv":              "SonyLIV",
    "sony liv":             "SonyLIV",
    "sony":                 "SonyLIV",
    "zee5":                 "Zee5",
    "zee 5":                "Zee5",
}

PERMITTED_OTT_NAMES: set = set(OTT_PROVIDER_IDS.values())

# ---------------------------------------------------------------------------
# TMDB API settings
# ---------------------------------------------------------------------------

TMDB_BASE_URL: str = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL: str = "https://image.tmdb.org/t/p/w342"
TMDB_MAX_PAGES: int = 3
TMDB_RATE_LIMIT_WARN: int = 450  # warn when approaching 500/run

# ---------------------------------------------------------------------------
# OMDb API settings
# ---------------------------------------------------------------------------

OMDB_BASE_URL: str = "https://www.omdbapi.com/"
OMDB_RATE_LIMIT_WARN: int = 450

# ---------------------------------------------------------------------------
# Retry settings
# ---------------------------------------------------------------------------

MAX_RETRIES: int = 3
RETRY_DELAYS: List[int] = [1, 2, 4]  # seconds between successive attempts

# ---------------------------------------------------------------------------
# Config dataclass with validation
# ---------------------------------------------------------------------------


@dataclass
class Config:
    """
    Holds all runtime configuration loaded from environment variables.

    Raises:
        EnvironmentError: If any required environment variable is absent or empty.
    """

    tmdb_api_key: str = field(default_factory=lambda: "")
    omdb_api_key: str = field(default_factory=lambda: "")
    gmail_address: str = field(default_factory=lambda: "")
    gmail_app_password: str = field(default_factory=lambda: "")
    recipient_email: str = field(default_factory=lambda: "")

    def __post_init__(self) -> None:
        """Load values from environment and validate that none are missing."""
        self.tmdb_api_key = self._require("TMDB_API_KEY")
        self.omdb_api_key = self._require("OMDB_API_KEY")
        self.gmail_address = self._require("GMAIL_ADDRESS")
        self.gmail_app_password = self._require("GMAIL_APP_PASSWORD")
        self.recipient_email = self._require("RECIPIENT_EMAIL")

    @staticmethod
    def _require(var: str) -> str:
        """
        Fetch a required environment variable.

        Args:
            var: The environment variable name.

        Returns:
            The non-empty string value of the variable.

        Raises:
            EnvironmentError: If the variable is absent or empty.
        """
        value = os.environ.get(var, "").strip()
        if not value:
            raise EnvironmentError(
                f"Required environment variable '{var}' is missing or empty. "
                f"Please set it in your .env file or environment before running."
            )
        return value


def load_config() -> Config:
    """
    Instantiate and return a validated Config object.

    Returns:
        A fully populated Config instance.

    Raises:
        EnvironmentError: Propagated from Config.__post_init__ if any var is missing.
    """
    return Config()
