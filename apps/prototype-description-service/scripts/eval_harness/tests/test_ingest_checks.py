"""FIR-11 Slice 1 — warn_scrape_signature firing and silence (TEST-15).

A firing fixture per family A–D (real CDN-shaped names) plus non-firing
camera-roll and normalized-slug fixtures. Proves the warning can fire and
can stay silent.
"""

from __future__ import annotations

from scripts.eval_harness.ingest_checks import ScrapeSignatureFamily, warn_scrape_signature

# Historical CDN-shaped original filenames (plan disposition table / census).
# These are ingest-time names; they do not exist on disk in this tree.
FAMILY_A_NAME = "quiet___elena_233787312_1809183585932731_2698952567892095846_n.jpg"
FAMILY_B_NAME = "alixiaxo__3747817309907040649.jpg"
FAMILY_C_NAME = "highlights_1234567890123.jpg"
FAMILY_D_NAME = "vscoa1b2c3d4e5f67890.jpg"

CAMERA_ROLL_NAME = "IMG_0249-rotated.jpg"
CAMERA_ROLL_WOULD_MATCH_B = "IMG_123456789012345.jpg"
NORMALIZED_SLUG = "opaline_beacon_375.jpg"
NORMALIZED_SLUG_CELEB = "anne_hathaway_11.jpg"


def test_family_a_fires_on_instagram_cdn_n_suffix() -> None:
    """Positive: family A matches a real Instagram-CDN ``…_n.jpg`` stem."""
    assert warn_scrape_signature(FAMILY_A_NAME) is ScrapeSignatureFamily.A
    # Same signal with a historical session directory prefix.
    assert (
        warn_scrape_signature(f"2026/07/{FAMILY_A_NAME}") is ScrapeSignatureFamily.A
    )


def test_family_b_fires_on_trailing_15plus_digit_run() -> None:
    """Positive: family B matches handle + 15+ digit CDN id."""
    assert warn_scrape_signature(FAMILY_B_NAME) is ScrapeSignatureFamily.B


def test_family_c_fires_on_highlights_prefix() -> None:
    """Positive: family C matches ``highlights_<10+ digits>``."""
    assert warn_scrape_signature(FAMILY_C_NAME) is ScrapeSignatureFamily.C
    assert warn_scrape_signature("highlights-12345678901.png") is ScrapeSignatureFamily.C


def test_family_d_fires_on_vsco_hex() -> None:
    """Positive: family D matches ``vsco`` + 10+ hex chars."""
    assert warn_scrape_signature(FAMILY_D_NAME) is ScrapeSignatureFamily.D


def test_camera_roll_img_0249_is_silent() -> None:
    """Negative: camera-roll ``IMG_0249-rotated.jpg``-style names do not fire."""
    assert warn_scrape_signature(CAMERA_ROLL_NAME) is None
    assert warn_scrape_signature("DSC_0005-scaled.jpg") is None
    assert warn_scrape_signature("PXL_20240101_123456.jpg") is None
    assert warn_scrape_signature("Screen Shot 2024-01-01 at 12.00.00.png") is None
    assert warn_scrape_signature("Screen-Shot-2024.png") is None


def test_camera_roll_prefix_excluded_even_when_digits_would_match_b() -> None:
    """Negative: camera-roll exclusion runs before family matching."""
    assert warn_scrape_signature(CAMERA_ROLL_WOULD_MATCH_B) is None


def test_normalized_slug_is_silent() -> None:
    """Negative: normalized ``<subject_slug>_<media_id>.<ext>`` stems do not fire.

    Family E (bare 15-char shortcodes) is dropped so ordinary slugs stay silent.
    """
    assert warn_scrape_signature(NORMALIZED_SLUG) is None
    assert warn_scrape_signature(NORMALIZED_SLUG_CELEB) is None
    assert warn_scrape_signature("personal/unlabeled_0603.jpg") is None


def test_family_e_style_shortcode_does_not_fire() -> None:
    """Family E is dropped: a bare 15-char slug must stay silent."""
    assert warn_scrape_signature("abcdefghijklmno.jpg") is None


def test_family_b_fourteen_digit_photo_stamp_is_silent() -> None:
    """Boundary: 14-digit photo_YYYYMMDDHHMMSS stays silent; 15+ still fires."""
    assert warn_scrape_signature("photo_20240101123045.jpg") is None
    assert warn_scrape_signature("photo_202401011230451.jpg") is ScrapeSignatureFamily.B


def test_family_c_nine_digit_highlights_is_silent() -> None:
    """Boundary: 9-digit highlights_ is silent; 10+ still fires."""
    assert warn_scrape_signature("highlights_123456789.jpg") is None
    assert warn_scrape_signature("highlights_1234567890.jpg") is ScrapeSignatureFamily.C


def test_family_d_nine_hex_vsco_is_silent() -> None:
    """Boundary: 9-hex vsco is silent; 10+ still fires."""
    assert warn_scrape_signature("vscoa1b2c3d4e.jpg") is None
    assert warn_scrape_signature("vscoa1b2c3d4e5.jpg") is ScrapeSignatureFamily.D


def test_family_a_o_suffix_fires() -> None:
    """Family A `_o` (not just `_n`) is a real Instagram CDN stem."""
    assert warn_scrape_signature("foo_123456_12345_o.jpg") is ScrapeSignatureFamily.A
    assert warn_scrape_signature("foo_123456_12345_n.jpg") is ScrapeSignatureFamily.A


def test_family_a_digit_floors() -> None:
    """Boundary: family A needs 6+ then 5+ digits; one-below stems stay silent.

    Kills `{6,}`→`{5,}` (5-digit first group) and `{5,}`→`{4,}` (4-digit
    second group). The firing 6/5-digit shape is the positive pair (TEST-15).
    """
    assert warn_scrape_signature("foo_123456_12345_n.jpg") is ScrapeSignatureFamily.A
    assert warn_scrape_signature("foo_12345_12345_n.jpg") is None
    assert warn_scrape_signature("foo_123456_1234_n.jpg") is None


def test_camera_roll_exclusion_covers_dsc_pxl_screen_shot_family_b_shapes() -> None:
    """DSC/PXL/Screen Shot names that would fire family B stay silent."""
    assert warn_scrape_signature("DSC_123456789012345.jpg") is None
    assert warn_scrape_signature("PXL_123456789012345.jpg") is None
    assert warn_scrape_signature("Screen-Shot-123456789012345.png") is None
    assert warn_scrape_signature("Screen Shot_123456789012345.png") is None


def test_camera_roll_exclusion_is_case_sensitive() -> None:
    """Plan census is case-sensitive; lowercase prefixes are not camera-roll."""
    assert warn_scrape_signature("img_123456789012345.jpg") is ScrapeSignatureFamily.B
    assert warn_scrape_signature("IMG_123456789012345.jpg") is None
