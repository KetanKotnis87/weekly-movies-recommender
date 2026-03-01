"""
PDF generator module for the Weekly Movie & Web Series Recommender.

Uses ReportLab exclusively (no WeasyPrint, no system dependencies).
Generates a polished PDF report with:
  - Cover page
  - Section headers per genre
  - Cards per content item with poster thumbnail, ratings, OTT platforms, etc.
  - Page footer with page number and generation date

All poster images are downloaded from the TMDB CDN and embedded;
failures fall back to a generated grey placeholder rectangle.
"""

import logging
import os
from datetime import date
from io import BytesIO
from typing import Dict, List, Optional

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from src.scorer import ContentItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

COLOUR_DARK_HEADER = colors.HexColor("#1a1a2e")
COLOUR_ACCENT = colors.HexColor("#e94560")
COLOUR_LIGHT_CARD = colors.HexColor("#f4f4f8")
COLOUR_WHITE = colors.white
COLOUR_MID_GREY = colors.HexColor("#cccccc")
COLOUR_DARK_GREY = colors.HexColor("#555555")
COLOUR_STAR_YELLOW = colors.HexColor("#f5a623")
COLOUR_SECTION_BG = colors.HexColor("#16213e")

# Page dimensions
PAGE_WIDTH, PAGE_HEIGHT = A4

# Poster thumbnail size in points (1 cm ≈ 28.35 pt)
POSTER_W = 80
POSTER_H = 120

# ---------------------------------------------------------------------------
# V2 view count formatter
# ---------------------------------------------------------------------------


def _format_views(views: int) -> str:
    """
    Format a view count as a human-readable string.

    Examples:
        3_500_000 → '3.5M views'
        750_000   → '750.0K views'
        999       → '999 views'

    Args:
        views: Raw integer view count (non-negative).

    Returns:
        Formatted string with unit suffix (M / K) or raw integer.
    """
    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M views"
    if views >= 1_000:
        return f"{views / 1_000:.1f}K views"
    return f"{views} views"


# ---------------------------------------------------------------------------
# Placeholder poster generator
# ---------------------------------------------------------------------------


def _generate_placeholder_bytes() -> bytes:
    """
    Generate a small grey placeholder image as PNG bytes.

    Returns:
        PNG-encoded bytes for a grey rectangle matching POSTER_W x POSTER_H.
    """
    img = PILImage.new("RGB", (POSTER_W * 2, POSTER_H * 2), color=(160, 160, 160))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_PLACEHOLDER_BYTES: bytes = _generate_placeholder_bytes()


# ---------------------------------------------------------------------------
# Utility: convert raw image bytes -> ReportLab Image flowable
# ---------------------------------------------------------------------------


def _make_image_flowable(
    image_bytes: Optional[bytes],
    width: float = POSTER_W,
    height: float = POSTER_H,
) -> Image:
    """
    Create a ReportLab Image flowable from raw bytes.

    Falls back to the placeholder on any error.

    Args:
        image_bytes: Raw image bytes (JPEG/PNG etc.) or None.
        width:       Display width in points.
        height:      Display height in points.

    Returns:
        A ReportLab Image flowable.
    """
    data = image_bytes or _PLACEHOLDER_BYTES
    try:
        buf = BytesIO(data)
        # Validate with Pillow first
        PILImage.open(buf).verify()
        buf.seek(0)
        return Image(buf, width=width, height=height)
    except Exception as exc:
        logger.warning("Image render error (%s); using placeholder.", exc)
        return Image(BytesIO(_PLACEHOLDER_BYTES), width=width, height=height)


# ---------------------------------------------------------------------------
# Overview truncation (mirrors scorer.py for self-containment)
# ---------------------------------------------------------------------------


def _truncate(text: str, max_chars: int = 120) -> str:
    """Truncate text to max_chars at the last word boundary, appending '...'."""
    if not text or not text.strip():
        return "No description available."
    text = text.strip()
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated + "..."


# ---------------------------------------------------------------------------
# Style registry
# ---------------------------------------------------------------------------


def _build_styles() -> Dict[str, ParagraphStyle]:
    """Build and return all paragraph styles used in the report."""
    base = getSampleStyleSheet()

    styles: Dict[str, ParagraphStyle] = {}

    styles["cover_title"] = ParagraphStyle(
        "cover_title",
        parent=base["Title"],
        fontSize=30,
        textColor=COLOUR_WHITE,
        spaceAfter=8,
        spaceBefore=0,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    styles["cover_subtitle"] = ParagraphStyle(
        "cover_subtitle",
        parent=base["Normal"],
        fontSize=13,
        textColor=COLOUR_MID_GREY,
        spaceAfter=6,
        alignment=TA_CENTER,
        fontName="Helvetica",
    )
    styles["cover_date"] = ParagraphStyle(
        "cover_date",
        parent=base["Normal"],
        fontSize=16,
        textColor=COLOUR_ACCENT,
        spaceAfter=4,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    styles["section_header"] = ParagraphStyle(
        "section_header",
        parent=base["Heading1"],
        fontSize=22,
        textColor=COLOUR_WHITE,
        spaceBefore=0,
        spaceAfter=6,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    styles["subsection_header"] = ParagraphStyle(
        "subsection_header",
        parent=base["Heading2"],
        fontSize=15,
        textColor=COLOUR_DARK_HEADER,
        spaceBefore=12,
        spaceAfter=6,
        fontName="Helvetica-Bold",
    )
    styles["card_title"] = ParagraphStyle(
        "card_title",
        parent=base["Normal"],
        fontSize=13,
        textColor=COLOUR_DARK_HEADER,
        fontName="Helvetica-Bold",
        spaceAfter=3,
    )
    styles["card_meta"] = ParagraphStyle(
        "card_meta",
        parent=base["Normal"],
        fontSize=9,
        textColor=COLOUR_DARK_GREY,
        fontName="Helvetica",
        spaceAfter=2,
    )
    styles["card_rating"] = ParagraphStyle(
        "card_rating",
        parent=base["Normal"],
        fontSize=10,
        textColor=COLOUR_DARK_HEADER,
        fontName="Helvetica-Bold",
        spaceAfter=2,
    )
    styles["card_overview"] = ParagraphStyle(
        "card_overview",
        parent=base["Normal"],
        fontSize=9,
        textColor=COLOUR_DARK_GREY,
        fontName="Helvetica-Oblique",
        spaceAfter=2,
        leading=13,
    )
    styles["badge"] = ParagraphStyle(
        "badge",
        parent=base["Normal"],
        fontSize=8,
        textColor=COLOUR_WHITE,
        fontName="Helvetica-Bold",
        spaceAfter=2,
    )
    styles["scarcity_note"] = ParagraphStyle(
        "scarcity_note",
        parent=base["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#8b4513"),
        fontName="Helvetica-Oblique",
        spaceBefore=6,
        spaceAfter=6,
    )
    styles["footer"] = ParagraphStyle(
        "footer",
        parent=base["Normal"],
        fontSize=8,
        textColor=COLOUR_MID_GREY,
        fontName="Helvetica",
        alignment=TA_CENTER,
    )
    styles["no_content"] = ParagraphStyle(
        "no_content",
        parent=base["Normal"],
        fontSize=10,
        textColor=COLOUR_DARK_GREY,
        fontName="Helvetica-Oblique",
        spaceBefore=4,
        spaceAfter=8,
    )

    return styles


# ---------------------------------------------------------------------------
# Card builder
# ---------------------------------------------------------------------------


def _build_card(item: ContentItem, styles: Dict[str, ParagraphStyle], bg_colour: colors.Color) -> Table:
    """
    Build a single recommendation card as a ReportLab Table.

    Layout:
      [ poster (left) | details (right) ]

    Args:
        item:      The ContentItem to render.
        styles:    Style registry from _build_styles().
        bg_colour: Background colour for this card.

    Returns:
        A Table flowable representing the card.
    """
    # -- Poster image --
    try:
        poster_img = _make_image_flowable(item.poster_image, width=POSTER_W, height=POSTER_H)
    except Exception:
        poster_img = _make_image_flowable(None, width=POSTER_W, height=POSTER_H)

    # -- Title + year --
    year = item.release_year or "N/A"
    title_para = Paragraph(
        f"{item.title} ({year})",
        styles["card_title"],
    )

    # -- Language badge (coloured background via markup) --
    lang_colours = {"hi": "#e94560", "en": "#0f3460", "kn": "#533483"}
    badge_bg = lang_colours.get(item.language, "#555555")
    badge_para = Paragraph(
        f'<font color="white"><b> {item.language_name} </b></font>',
        styles["badge"],
    )
    badge_table = Table(
        [[badge_para]],
        colWidths=[55],
    )
    badge_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(badge_bg)),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))

    # -- Category (Movie / Web Series) --
    category_label = "Movie" if item.media_type == "movie" else "Web Series"
    category_para = Paragraph(f"<b>Category:</b> {category_label}", styles["card_meta"])

    # -- IMDB rating --
    if item.imdb_rating is not None:
        rating_str = f"&#9733; IMDB: {item.imdb_rating:.1f}/10"
    else:
        rating_str = "&#9733; IMDB: N/A"
    rating_para = Paragraph(rating_str, styles["card_rating"])

    # -- TMDB popularity --
    popularity_para = Paragraph(
        f"TMDB Popularity: {item.tmdb_popularity:.1f}",
        styles["card_meta"],
    )

    # -- OTT platforms --
    if item.ott_platforms:
        ott_str = ", ".join(item.ott_platforms)
    else:
        ott_str = "Not confirmed on major OTT"
    ott_para = Paragraph(f"<b>Platform:</b> {ott_str}", styles["card_meta"])

    # -- V2: Google Trends score (UC-019) --
    # Render "Trending: N/100" when trends score is available (including 0).
    trends_para = None
    if item.google_trends_score is not None:
        trends_para = Paragraph(
            f"Trending: {item.google_trends_score:.0f}/100",
            styles["card_meta"],
        )

    # -- V2: YouTube trailer views (UC-019) --
    # Render "Trailer: X.XM views" only when views > 0.
    youtube_para = None
    if item.youtube_views is not None and item.youtube_views > 0:
        youtube_para = Paragraph(
            f"Trailer: {_format_views(item.youtube_views)}",
            styles["card_meta"],
        )

    # -- Teaser overview --
    overview_para = Paragraph(
        f"<i>{_truncate(item.overview)}</i>",
        styles["card_overview"],
    )

    # Assemble the right-column content
    right_content = [
        title_para,
        badge_table,
        Spacer(1, 4),
        category_para,
        rating_para,
        popularity_para,
        ott_para,
    ]
    if trends_para is not None:
        right_content.append(trends_para)
    if youtube_para is not None:
        right_content.append(youtube_para)
    right_content.extend([
        Spacer(1, 4),
        overview_para,
    ])

    # Build a nested table for the right column
    right_table = Table(
        [[block] for block in right_content],
        colWidths=[PAGE_WIDTH - 2 * cm - POSTER_W - 12],
    )
    right_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    # Outer card table: [poster | spacer | details]
    card = Table(
        [[poster_img, Spacer(10, 1), right_table]],
        colWidths=[POSTER_W, 10, None],
        rowHeights=[POSTER_H + 10],
    )
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg_colour),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        # Apply outer padding to poster (col 0) and details (col 2) only
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (0, -1), 8),    # poster left
        ("RIGHTPADDING", (2, 0), (2, -1), 8),   # details right
        # Spacer column (col 1): zero padding so it fits in the 10pt column
        ("LEFTPADDING", (1, 0), (1, -1), 0),
        ("RIGHTPADDING", (1, 0), (1, -1), 0),
        # Left padding for details column
        ("LEFTPADDING", (2, 0), (2, -1), 0),
        # Right padding for poster column
        ("RIGHTPADDING", (0, 0), (0, -1), 0),
        ("BOX", (0, 0), (-1, -1), 0.5, COLOUR_MID_GREY),
    ]))
    return card


# ---------------------------------------------------------------------------
# PDF Report class
# ---------------------------------------------------------------------------


class PDFReport:
    """
    Generates the weekly watch list PDF using ReportLab.

    Usage:
        report = PDFReport()
        report.generate(recommendations, output_path)
    """

    def __init__(self) -> None:
        self._styles: Dict[str, ParagraphStyle] = _build_styles()

    def generate(
        self,
        recommendations: Dict[str, Dict[str, List[ContentItem]]],
        output_path: str,
        run_date: Optional[date] = None,
    ) -> str:
        """
        Build and save the PDF report.

        Args:
            recommendations: Nested dict:
                {
                  'movies': { genre_name: [ContentItem, ...], ... },
                  'series': { genre_name: [ContentItem, ...], ... },
                }
            output_path: Absolute filesystem path for the output PDF.
            run_date:    The Saturday execution date; defaults to today.

        Returns:
            The output_path string (for chaining / logging).
        """
        if run_date is None:
            run_date = date.today()

        formatted_date = run_date.strftime("Saturday, %d %B %Y")
        report_date_str = run_date.strftime("%d %B %Y")

        # Count stats for cover page
        movie_recs = recommendations.get("movies", {})
        series_recs = recommendations.get("series", {})
        total_items = sum(len(v) for v in movie_recs.values()) + sum(len(v) for v in series_recs.values())
        kn_items = sum(
            1 for bucket in (movie_recs, series_recs)
            for items in bucket.values()
            for item in items
            if item.language == "kn"
        )

        # Build story (list of flowables)
        story = []

        # -- Cover page --
        story.extend(self._build_cover(formatted_date, total_items, kn_items))

        # -- Genre sections --
        from src.config import GENRE_ORDER
        for genre in GENRE_ORDER:
            genre_movies = movie_recs.get(genre, [])
            genre_series = series_recs.get(genre, [])

            if not genre_movies and not genre_series:
                logger.debug("No content for genre '%s'; skipping section.", genre)
                continue

            story.extend(self._build_genre_section(genre, genre_movies, genre_series))

        # -- Build document --
        doc = self._create_doc(output_path, report_date_str)
        doc.build(story)

        file_size_kb = os.path.getsize(output_path) // 1024
        logger.info(
            "PDF generated: %s | size: %d KB",
            output_path, file_size_kb,
        )
        if file_size_kb > 10 * 1024:
            logger.warning(
                "PDF size %d KB exceeds 10 MB threshold — check NFR-004.",
                file_size_kb,
            )

        return output_path

    # ------------------------------------------------------------------
    # Document template
    # ------------------------------------------------------------------

    def _create_doc(self, output_path: str, report_date_str: str = "") -> BaseDocTemplate:
        """
        Create the ReportLab BaseDocTemplate with a single-frame page template.

        The footer is drawn via the PageTemplate.afterDrawPage callback, which is
        the correct approach for BaseDocTemplate (unlike SimpleDocTemplate which
        accepts onFirstPage/onLaterPages kwargs in build()).

        Args:
            output_path:      Filesystem path for the output PDF.
            report_date_str:  Formatted date string for the footer (e.g. '01 March 2026').

        Returns:
            A configured BaseDocTemplate instance.
        """
        left_margin = right_margin = 1 * cm
        top_margin = bottom_margin = 1.5 * cm

        doc = BaseDocTemplate(
            output_path,
            pagesize=A4,
            leftMargin=left_margin,
            rightMargin=right_margin,
            topMargin=top_margin,
            bottomMargin=bottom_margin,
        )

        frame = Frame(
            left_margin,
            bottom_margin,
            PAGE_WIDTH - left_margin - right_margin,
            PAGE_HEIGHT - top_margin - bottom_margin,
            id="main",
        )

        def _draw_footer(canvas, doc):
            canvas.saveState()
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(COLOUR_MID_GREY)
            footer_text = (
                f"Page {doc.page}  |  Generated on {report_date_str}  |  "
                f"Weekly Watch List"
            )
            canvas.drawCentredString(PAGE_WIDTH / 2, 18, footer_text)
            canvas.restoreState()

        doc.addPageTemplates([
            PageTemplate(id="main", frames=[frame], onPage=_draw_footer)
        ])
        return doc

    # ------------------------------------------------------------------
    # Cover page
    # ------------------------------------------------------------------

    def _build_cover(
        self, formatted_date: str, total_items: int, kn_count: int
    ) -> list:
        """
        Build the cover page flowables.

        Args:
            formatted_date: The date string for display (e.g. 'Saturday, 01 March 2026').
            total_items:    Total number of recommendations in this report.
            kn_count:       Number of Kannada-language items in the final selection.

        Returns:
            List of ReportLab flowables.
        """
        story = []

        # Dark header background block (simulated with a table)
        cover_bg = Table(
            [[
                Paragraph("Your Weekly Watch List", self._styles["cover_title"])
            ]],
            colWidths=[PAGE_WIDTH - 2 * cm],
            rowHeights=[60],
        )
        cover_bg.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), COLOUR_DARK_HEADER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 16),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ]))
        story.append(Spacer(1, 20))
        story.append(cover_bg)
        story.append(Spacer(1, 12))
        story.append(Paragraph(formatted_date, self._styles["cover_date"]))
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            f"{total_items} curated picks across Action, Thriller, Drama & Comedy — "
            "Hindi | English | Kannada",
            self._styles["cover_subtitle"],
        ))
        story.append(Spacer(1, 8))
        story.append(HRFlowable(width="100%", thickness=1, color=COLOUR_ACCENT))
        story.append(Spacer(1, 12))

        if kn_count == 0:
            story.append(Paragraph(
                "Note: No Kannada-language titles met the quality and recency criteria this week. "
                "Recommendations shown are in Hindi and/or English.",
                self._styles["scarcity_note"],
            ))
            story.append(Spacer(1, 8))

        story.append(PageBreak())
        return story

    # ------------------------------------------------------------------
    # Genre section
    # ------------------------------------------------------------------

    def _build_genre_section(
        self,
        genre: str,
        movies: List[ContentItem],
        series: List[ContentItem],
    ) -> list:
        """
        Build the flowables for a single genre section.

        Args:
            genre:   Genre name (e.g. 'Action').
            movies:  Up to 3 movie ContentItems for this genre.
            series:  Up to 3 TV series ContentItems for this genre.

        Returns:
            List of ReportLab flowables.
        """
        story = []

        # Genre header block
        genre_header_table = Table(
            [[Paragraph(genre.upper(), self._styles["section_header"])]],
            colWidths=[PAGE_WIDTH - 2 * cm],
            rowHeights=[50],
        )
        genre_header_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), COLOUR_SECTION_BG),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ]))
        story.append(genre_header_table)
        story.append(Spacer(1, 10))

        # Movies subsection
        if movies:
            story.extend(self._build_subsection("MOVIES", movies, genre))

        # Series subsection
        if series:
            story.extend(self._build_subsection("WEB SERIES", series, genre))

        story.append(PageBreak())
        return story

    # ------------------------------------------------------------------
    # Subsection (MOVIES or WEB SERIES) within a genre
    # ------------------------------------------------------------------

    def _build_subsection(
        self,
        label: str,
        items: List[ContentItem],
        genre: str,
    ) -> list:
        """
        Build the flowables for a MOVIES or WEB SERIES subsection.

        Args:
            label: 'MOVIES' or 'WEB SERIES'.
            items: List of ContentItem objects to render as cards.
            genre: Genre name (for log messages and scarcity note).

        Returns:
            List of ReportLab flowables.
        """
        story = []
        story.append(Paragraph(label, self._styles["subsection_header"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=COLOUR_MID_GREY))
        story.append(Spacer(1, 6))

        if len(items) < 3:
            lang_names = {item.language for item in items}
            missing_langs = {"hi", "en", "kn"} - lang_names
            if missing_langs:
                kn_absent = "kn" not in lang_names and kn_count_in_genre(items) == 0
                if kn_absent:
                    story.append(Paragraph(
                        "Kannada content sparse — showing best available.",
                        self._styles["scarcity_note"],
                    ))
                else:
                    story.append(Paragraph(
                        f"Limited content available this week for {genre} {label.title()}.",
                        self._styles["scarcity_note"],
                    ))

        for idx, item in enumerate(items):
            bg = COLOUR_LIGHT_CARD if idx % 2 == 0 else COLOUR_WHITE
            try:
                card = _build_card(item, self._styles, bg)
                story.append(card)
                story.append(Spacer(1, 8))
            except Exception as exc:
                logger.error(
                    "Card render failed for '%s' (%s). Attempting fallback. Error: %s",
                    item.title, item.id, exc,
                )
                try:
                    # Fallback: clear poster_image and retry with placeholder
                    item.poster_image = None
                    card = _build_card(item, self._styles, bg)
                    story.append(card)
                    story.append(Spacer(1, 8))
                except Exception as exc2:
                    logger.error(
                        "Fallback card render also failed for '%s'. Omitting card. Error: %s",
                        item.title, exc2,
                    )

        story.append(Spacer(1, 10))
        return story


# ---------------------------------------------------------------------------
# Standalone helper
# ---------------------------------------------------------------------------


def kn_count_in_genre(items: List[ContentItem]) -> int:
    """Count Kannada-language items in a list."""
    return sum(1 for item in items if item.language == "kn")


# ---------------------------------------------------------------------------
# Public convenience function
# ---------------------------------------------------------------------------


def generate_pdf(
    recommendations: Dict[str, Dict[str, List[ContentItem]]],
    output_path: str,
    run_date: Optional[date] = None,
) -> str:
    """
    Generate the weekly PDF report.

    Args:
        recommendations: Dict with keys 'movies' and 'series', each mapping
                         genre names to lists of ContentItem objects.
        output_path:     Absolute path for the output PDF file.
        run_date:        Execution date (defaults to today).

    Returns:
        The output_path string.
    """
    report = PDFReport()
    return report.generate(recommendations, output_path, run_date=run_date)
