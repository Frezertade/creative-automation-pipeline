"""
Image processing engine for the Creative Automation Pipeline.

Handles loading input images, creating GenAI placeholders, resizing,
text overlays, and saving final creatives.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from src import genai
from src.config import (
    ASPECT_RATIOS,
    DEFAULT_BRAND_COLOR,
    FONT_COLOR,
    FONT_PATH_DEFAULT,
    INPUT_DIR,
    OUTPUT_DIR,
    OVERLAY_HEIGHT_RATIO,
    OVERLAY_OPACITY,
    PLACEHOLDER_BG_COLOR,
    PLACEHOLDER_GRADIENT,
    PLACEHOLDER_TEXT,
)
from src.models import Campaign, Product

GENAI_CACHE_DIR = INPUT_DIR / ".genai"

# Per-process set of product names whose GenAI call already failed this run.
# Avoids hammering the API 3x (once per ratio) when the first call errors.
_genai_failed: set[str] = set()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------
def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a TrueType font, falling back to PIL default."""
    if FONT_PATH_DEFAULT and os.path.isfile(FONT_PATH_DEFAULT):
        return ImageFont.truetype(FONT_PATH_DEFAULT, size)
    # Try common system fonts
    for path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Placeholder generation
# ---------------------------------------------------------------------------
def create_placeholder(
    width: int, height: int, brand_color: Optional[str] = None
) -> Image.Image:
    """
    Create a visually appealing placeholder for GenAI image generation.

    Uses the brand colour as an accent, with a dark gradient background
    and clean typography indicating a GenAI image will be produced here.
    """
    img = Image.new("RGB", (width, height), PLACEHOLDER_BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Parse brand colour accent
    accent: Tuple[int, int, int] = (60, 60, 60)
    if brand_color:
        hex_col = brand_color.lstrip("#")
        try:
            accent = tuple(int(hex_col[i : i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            accent = (60, 60, 60)

    # --- Gradient overlay (top → bottom: dark → brand accent) ---
    if PLACEHOLDER_GRADIENT:
        for y in range(height):
            blend = y / height
            r = int(PLACEHOLDER_BG_COLOR[0] * (1 - blend) + accent[0] * blend)
            g = int(PLACEHOLDER_BG_COLOR[1] * (1 - blend) + accent[1] * blend)
            b = int(PLACEHOLDER_BG_COLOR[2] * (1 - blend) + accent[2] * blend)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

    # --- Grid pattern (subtle) ---
    grid_color = (255, 255, 255, 12)
    grid_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(grid_overlay)
    step = 60
    for x in range(0, width, step):
        gdraw.line([(x, 0), (x, height)], fill=grid_color, width=1)
    for y in range(0, height, step):
        gdraw.line([(0, y), (width, y)], fill=grid_color, width=1)
    img = Image.alpha_composite(img.convert("RGBA"), grid_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # --- Central icon (sparkle/diamond shape) ---
    cx, cy = width // 2, height // 2 - 40
    icon_size = min(width, height) // 12
    sparkle_color = (255, 255, 255, 180)
    sparkle = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(sparkle)
    # Four-point star
    pts = [
        (cx, cy - icon_size),
        (cx + icon_size // 3, cy - icon_size // 3),
        (cx + icon_size, cy),
        (cx + icon_size // 3, cy + icon_size // 3),
        (cx, cy + icon_size),
        (cx - icon_size // 3, cy + icon_size // 3),
        (cx - icon_size, cy),
        (cx - icon_size // 3, cy - icon_size // 3),
    ]
    sdraw.polygon(pts, fill=sparkle_color)
    img = Image.alpha_composite(img.convert("RGBA"), sparkle).convert("RGB")
    draw = ImageDraw.Draw(img)

    # --- Placeholder text ---
    font_size = max(24, min(width, height) // 20)
    font = _get_font(font_size)
    text = PLACEHOLDER_TEXT
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (width - tw) // 2
    ty = cy + icon_size + 30
    # Text shadow
    draw.text((tx + 2, ty + 2), text, font=font, fill=(0, 0, 0, 128))
    draw.text((tx, ty), text, font=font, fill=(255, 255, 255, 220))

    # Sub-label
    sub_font = _get_font(font_size // 2)
    sub_text = "AI-generated image will be inserted here"
    bbox2 = draw.textbbox((0, 0), sub_text, font=sub_font)
    sw = bbox2[2] - bbox2[0]
    draw.text(
        ((width - sw) // 2, ty + font_size + 10),
        sub_text,
        font=sub_font,
        fill=(200, 200, 200, 180),
    )

    return img.convert("RGB")


# ---------------------------------------------------------------------------
# Image loading & resizing
# ---------------------------------------------------------------------------
def load_product_image(
    product: Product, campaign: Campaign, width: int, height: int
) -> Image.Image:
    """
    Load a product image from ``data/inputs/`` or create a placeholder.

    Falls back to the first available uploaded image if the product has
    no specific image set, so uploading *any* image "just works".

    When generating for multiple products in the same campaign, already-used
    fallback images are tracked to distribute distinct images across products.

    Args:
        product: The product being processed.
        campaign: Parent campaign (used for brand colour).
        width, height: Target output dimensions.

    Returns:
        A PIL Image sized to (width, height).
    """
    brand_color = campaign.brand_color or DEFAULT_BRAND_COLOR
    image_name = product.image

    # 1. Try the explicitly named image
    if image_name:
        candidate = INPUT_DIR / image_name
        if candidate.is_file():
            try:
                logger.info("Loading image: %s", candidate)
                img = Image.open(candidate).convert("RGB")
                return resize_contain(img, width, height)
            except Exception as e:
                logger.warning("Failed to open image %s: %s — checking fallbacks", candidate, e)
        else:
            logger.warning("Image not found: %s — checking fallbacks", candidate)

    # 2. Fallback: find an uploaded image not already used by another product
    #    This distributes distinct images across products without explicit assignment.
    uploaded = sorted(INPUT_DIR.glob("*"))
    # Collect images already assigned to OTHER products in the same campaign
    assigned_to_others: set[str] = set()
    for p in campaign.products:
        if p.image and p.name != product.name:
            assigned_to_others.add(p.image)
    # Try unassigned images first, then any image
    candidates = [f for f in uploaded if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    # Sort: images NOT assigned to other products first, then the rest
    candidates.sort(key=lambda f: f.name in assigned_to_others)

    for f in candidates:
        if image_name and f.name == image_name:
            continue  # already tried above
        logger.info("Fallback: using uploaded image %s for %s", f.name, product.name)
        try:
            img = Image.open(f).convert("RGB")
            return resize_contain(img, width, height)
        except Exception as e:
            logger.warning("Failed to open fallback image %s: %s", f.name, e)
            continue

    # 3. No image at all → try GenAI (cached per-product), then placeholder
    if genai.is_enabled() and product.name not in _genai_failed:
        cache_path = _genai_cache_path(product.name)
        if not cache_path.is_file():
            prompt = genai.build_prompt(
                product.name,
                product.message,
                campaign.campaign_message,
                campaign.target_region,
            )
            image_bytes = genai.generate_hero_image(prompt)
            if image_bytes:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(image_bytes)
                logger.info("GenAI image cached: %s", cache_path)
            else:
                _genai_failed.add(product.name)
        if cache_path.is_file():
            try:
                img = Image.open(cache_path).convert("RGB")
                return resize_contain(img, width, height)
            except Exception as e:
                logger.warning("Failed to open cached GenAI image %s: %s", cache_path, e)

    logger.info("No image available for %s — using placeholder", product.name)
    return create_placeholder(width, height, brand_color)


def _genai_cache_path(product_name: str) -> Path:
    """Per-product cache path so one GenAI call serves all 3 ratios."""
    slug = "".join(c if c.isalnum() else "_" for c in product_name.lower()).strip("_")
    return GENAI_CACHE_DIR / f"{slug}.png"


def resize_contain(img: Image.Image, target_w: int, target_h: int, bg_color: tuple = (30, 30, 30)) -> Image.Image:
    """
    Resize *img* to fit within *target_w* × *target_h* while preserving aspect ratio.

    The entire image is visible — no cropping. Extra space is filled with
    *bg_color* so the result is exactly *target_w* × *target_h*.
    Analogous to CSS ``object-fit: contain``.
    """
    src_w, src_h = img.size
    src_ratio = src_w / src_h
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        # Source is wider — match widths, height will be shorter
        new_w = target_w
        new_h = int(target_w / src_ratio)
    else:
        # Source is taller — match heights, width will be narrower
        new_h = target_h
        new_w = int(target_h * src_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Create background canvas and paste image centered
    canvas = Image.new("RGB", (target_w, target_h), bg_color)
    left = (target_w - new_w) // 2
    top = (target_h - new_h) // 2
    canvas.paste(img, (left, top))
    return canvas


# ---------------------------------------------------------------------------
# Text overlay
# ---------------------------------------------------------------------------
def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    y: int,
    max_width: int,
    fill: Tuple[int, int, int, int] = (255, 255, 255, 255),
    shadow: bool = True,
):
    """Draw text centred horizontally at *y* with optional shadow."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    x = (max_width - tw) // 2
    if shadow:
        draw.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 160))
    draw.text((x, y), text, font=font, fill=fill)


def _wrap_text(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> List[str]:
    """Word-wrap *text* to fit *max_width* pixels."""
    words = text.split()
    if not words:
        return [""]
    lines: List[str] = []
    current = words[0]
    for w in words[1:]:
        test = f"{current} {w}"
        bbox = draw.textbbox((0, 0), test, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            current = test
        else:
            lines.append(current)
            current = w
    lines.append(current)
    return lines


def apply_overlay(
    img: Image.Image,
    campaign: Campaign,
    product: Product,
) -> Image.Image:
    """
    Add a semi-transparent overlay bar at the bottom and render all text.
    """
    width, height = img.size
    brand_color = campaign.brand_color or DEFAULT_BRAND_COLOR
    hex_col = brand_color.lstrip("#")
    accent_rgb = tuple(int(hex_col[i : i + 2], 16) for i in (0, 2, 4))

    # --- Overlay bar ---
    bar_height = int(height * OVERLAY_HEIGHT_RATIO)
    overlay = Image.new("RGBA", (width, bar_height), (*accent_rgb, int(255 * OVERLAY_OPACITY)))
    # Slight gradient on bar: darker at bottom
    for y in range(bar_height):
        blend = y / bar_height
        alpha = int(255 * OVERLAY_OPACITY * (0.85 + 0.15 * blend))
        overlay.putpixel((0, y), (*accent_rgb, alpha))
        overlay.putpixel((width - 1, y), (*accent_rgb, alpha))

    img = img.convert("RGBA")
    img.paste(overlay, (0, height - bar_height), overlay)
    draw = ImageDraw.Draw(img)

    # --- Sizing ---
    base_font_size = max(20, int(height * 0.045))
    padding = int(width * 0.04)
    usable_width = width - 2 * padding
    y_cursor = height - bar_height + int(padding * 0.6)

    # --- 1. Product name (small, uppercase, muted) ---
    name_font = _get_font(int(base_font_size * 0.55))
    name_text = product.name.upper()
    bbox = draw.textbbox((0, 0), name_text, font=name_font)
    _draw_centered_text(draw, name_text, name_font, y_cursor, width, fill=(220, 220, 220, 255))
    y_cursor += bbox[3] - bbox[1] + 4

    # --- 2. Product message (bold, prominent) ---
    msg_font = _get_font(base_font_size)
    wrapped = _wrap_text(product.message, msg_font, usable_width, draw)
    for line in wrapped:
        _draw_centered_text(draw, line, msg_font, y_cursor, width, fill=FONT_COLOR)
        bbox = draw.textbbox((0, 0), line, font=msg_font)
        y_cursor += bbox[3] - bbox[1] + 2

    y_cursor += 4

    # --- 3. Features (bullet list) ---
    feat_font = _get_font(int(base_font_size * 0.5))
    for feat in product.features:
        feat_line = f"• {feat}"
        bbox = draw.textbbox((0, 0), feat_line, font=feat_font)
        # Left-aligned with padding
        x_feat = padding
        draw.text((x_feat + 1, y_cursor + 1), feat_line, font=feat_font, fill=(0, 0, 0, 160))
        draw.text((x_feat, y_cursor), feat_line, font=feat_font, fill=(255, 255, 255, 240))
        y_cursor += bbox[3] - bbox[1] + 2

    y_cursor += 4

    # --- 4. CTA button (simulated) ---
    cta_font = _get_font(int(base_font_size * 0.55))
    cta_text = f"▸ {product.cta} ◂"
    cta_bbox = draw.textbbox((0, 0), cta_text, font=cta_font)
    cta_w = cta_bbox[2] - cta_bbox[0]
    cta_h = cta_bbox[3] - cta_bbox[1]
    cta_x = (width - cta_w) // 2 - 20
    cta_y = y_cursor
    # CTA background pill
    pad = 8
    draw.rounded_rectangle(
        [cta_x - pad, cta_y - pad // 2, cta_x + cta_w + pad, cta_y + cta_h + pad // 2],
        radius=12,
        fill=(255, 255, 255, 50),
        outline=(255, 255, 255, 180),
    )
    draw.text((cta_x, cta_y), cta_text, font=cta_font, fill=(255, 255, 255, 255))

    # --- 5. Campaign message (top of image, subtle) ---
    top_font = _get_font(int(base_font_size * 0.5))
    top_msg = campaign.campaign_message
    bbox = draw.textbbox((0, 0), top_msg, font=top_font)
    tw = bbox[2] - bbox[0]
    draw.text(
        ((width - tw) // 2 + 1, 11),
        top_msg,
        font=top_font,
        fill=(0, 0, 0, 160),
    )
    draw.text(
        ((width - tw) // 2, 10),
        top_msg,
        font=top_font,
        fill=(255, 255, 255, 220),
    )

    return img.convert("RGB")


# ---------------------------------------------------------------------------
# Main generation pipeline
# ---------------------------------------------------------------------------
def generate_creative(
    campaign: Campaign,
    product: Product,
    ratio_name: str,
    output_dir: Path,
) -> Path:
    """
    Generate a single creative asset for one product at one aspect ratio.

    Args:
        campaign: The campaign brief.
        product: The product to generate for.
        ratio_name: Key from ASPECT_RATIOS (e.g. ``"1:1"``).
        output_dir: Directory to save the output in.

    Returns:
        Path to the saved image.
    """
    target_w, target_h = ASPECT_RATIOS[ratio_name]

    # 1. Load or create base image
    img = load_product_image(product, campaign, target_w, target_h)

    # 2. Apply overlay and text
    img = apply_overlay(img, campaign, product)

    # 3. Save
    safe_name = product.name.lower().replace(" ", "_").replace("/", "_")
    filename = f"{safe_name}_{ratio_name.replace(':', '_')}.png"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    img.save(path, "PNG")
    logger.info("Saved: %s", path)
    return path


def generate_all_creatives(campaign: Campaign) -> Dict[str, Dict[str, List[Path]]]:
    """
    Generate creatives for every product × aspect ratio.

    Returns:
        Nested dict: ``{product_name: {ratio_name: [Path, ...]}}``
    """
    results: Dict[str, Dict[str, List[Path]]] = {}
    campaign_dir = OUTPUT_DIR / _safe_dirname(campaign.campaign_name)

    for product in campaign.products:
        product_dir = campaign_dir / _safe_dirname(product.name)
        results[product.name] = {}

        for ratio_name in ASPECT_RATIOS:
            ratio_dir = product_dir / ratio_name.replace(":", "_")
            path = generate_creative(campaign, product, ratio_name, ratio_dir)
            results[product.name].setdefault(ratio_name, []).append(path)

    logger.info(
        "Generation complete — %d products × %d ratios",
        len(campaign.products),
        len(ASPECT_RATIOS),
    )
    return results


def _safe_dirname(name: str) -> str:
    """Sanitise a string for use as a directory name."""
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip().replace(" ", "_")
