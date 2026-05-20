"""
Configuration module for the Creative Automation Pipeline.

Centralizes all constants, paths, and settings used across the application.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
INPUT_DIR = DATA_DIR / "inputs"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
SAMPLE_CAMPAIGN_PATH = DATA_DIR / "sample_campaign.json"

# Ensure directories exist
for _dir in [DATA_DIR, INPUT_DIR, OUTPUT_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Aspect ratios & output dimensions
# ---------------------------------------------------------------------------
ASPECT_RATIOS = {
    "1:1": (1080, 1080),
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}

# Named aliases
RATIO_SQUARE = "1:1"
RATIO_PORTRAIT = "9:16"
RATIO_LANDSCAPE = "16:9"

# ---------------------------------------------------------------------------
# Text overlay settings
# ---------------------------------------------------------------------------
OVERLAY_HEIGHT_RATIO = 0.25  # fraction of image height reserved for text
OVERLAY_OPACITY = 0.60       # alpha for the overlay bar
FONT_SIZE_RATIO = 0.055      # campaign message font size = height * ratio
FONT_COLOR = (255, 255, 255)  # white
FONT_PATH_DEFAULT = None      # None = use PIL default

# ---------------------------------------------------------------------------
# Brand defaults (used when campaign doesn't specify)
# ---------------------------------------------------------------------------
DEFAULT_BRAND_COLOR = "#1a73e8"
DEFAULT_SECONDARY_COLOR = "#34a853"

# ---------------------------------------------------------------------------
# Placeholder settings (when input images are missing)
# ---------------------------------------------------------------------------
PLACEHOLDER_BG_COLOR = (30, 30, 30)
PLACEHOLDER_GRADIENT = True  # subtle gradient on placeholder
PLACEHOLDER_TEXT = "✨ GenAI Image Generation Placeholder"

# ---------------------------------------------------------------------------
# Validator / legal settings
# ---------------------------------------------------------------------------
# Prohibited words to flag in legal content check
PROHIBITED_WORDS = [
    "guaranteed", "guarantee", "100%", "free money",
    "no risk", "risk-free", "limited time only", "act now",
    "click here", "exclusive deal", "buy now",
    "instant", "miracle", "cure",
]

# Minimum font size in pixels before we flag as "hard to read"
MIN_FONT_SIZE_PX = 20

# ---------------------------------------------------------------------------
# Web server settings
# ---------------------------------------------------------------------------
WEB_HOST = "0.0.0.0"
WEB_PORT = 8000

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
