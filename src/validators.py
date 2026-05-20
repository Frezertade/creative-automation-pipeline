"""
QA / Validation pipeline for generated creative assets.

Runs checks on all output images and produces a structured report:
  - Image existence & count
  - Dimension validation
  - Brand compliance (logo presence via OpenCV template matching, brand colours)
  - Text visibility (contrast, clipping)
  - Image quality (blur detection via Laplacian variance)
  - Legal content flagging
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from src.config import (
    ASPECT_RATIOS,
    PROHIBITED_WORDS,
    OUTPUT_DIR,
)
from src.models import Campaign

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------
class ValidationReport:
    """Structured QA report."""

    def __init__(self, campaign_name: str):
        self.campaign_name = campaign_name
        self.total_images = 0
        self.dimension_checks: List[Dict[str, Any]] = []
        self.brand_checks: List[Dict[str, Any]] = []
        self.text_checks: List[Dict[str, Any]] = []
        self.quality_checks: List[Dict[str, Any]] = []
        self.legal_flags: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self.summary: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_name": self.campaign_name,
            "total_images": self.total_images,
            "dimension_checks": self.dimension_checks,
            "brand_checks": self.brand_checks,
            "text_checks": self.text_checks,
            "quality_checks": self.quality_checks,
            "legal_flags": self.legal_flags,
            "errors": self.errors,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _find_output_images(campaign: Campaign) -> List[Path]:
    """Walk the output directory and collect all generated PNGs."""
    campaign_dir = OUTPUT_DIR / _safe_dirname(campaign.campaign_name)
    if not campaign_dir.is_dir():
        return []
    return list(campaign_dir.rglob("*.png"))


def _safe_dirname(name: str) -> str:
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip().replace(" ", "_")


def _infer_ratio_from_path(path: Path) -> str:
    """Guess aspect ratio from directory name (e.g. '1_1' -> '1:1')."""
    for part in path.parts:
        cleaned = part.replace("_", ":")
        if cleaned in ASPECT_RATIOS:
            return cleaned
    return "unknown"


def _pil_to_cv2(pil_img: Image.Image) -> np.ndarray:
    """Convert a PIL RGB image to an OpenCV BGR array."""
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def _cv2_to_pil(cv_img: np.ndarray) -> Image.Image:
    """Convert an OpenCV BGR array to a PIL RGB image."""
    return Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB))


# ---------------------------------------------------------------------------
# 1. Dimension validation
# ---------------------------------------------------------------------------
def check_dimensions(image_path: Path, ratio_name: str) -> Dict[str, Any]:
    """Verify the image matches expected dimensions for its aspect ratio."""
    result = {"path": str(image_path), "ratio": ratio_name, "pass": False, "details": {}}
    try:
        with Image.open(image_path) as img:
            w, h = img.size
            expected_w, expected_h = ASPECT_RATIOS.get(ratio_name, (0, 0))
            result["details"] = {
                "actual": f"{w}x{h}",
                "expected": f"{expected_w}x{expected_h}",
            }
            if w == expected_w and h == expected_h:
                result["pass"] = True
            else:
                result["details"]["error"] = f"Expected {expected_w}x{expected_h}, got {w}x{h}"
    except Exception as e:
        result["details"]["error"] = str(e)
    return result


# ---------------------------------------------------------------------------
# 2. Brand compliance with OpenCV
# ---------------------------------------------------------------------------
def check_brand_compliance(
    image_path: Path, campaign: Campaign
) -> Dict[str, Any]:
    """
    Brand compliance checks using OpenCV:
      - Logo presence via template matching (if logo file provided & exists)
      - Brand colour dominance in the image
    """
    result = {"path": str(image_path), "pass": True, "checks": []}
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError("Could not read image with OpenCV")
        h, w = img.shape[:2]

        # --- Logo detection via template matching ---
        if campaign.logo_path:
            logo_file = Path(campaign.logo_path)
            if logo_file.is_file():
                logo_cv = cv2.imread(str(logo_file))
                if logo_cv is not None:
                    lh, lw = logo_cv.shape[:2]
                    if lw <= w and lh <= h:
                        # Multi-scale template matching
                        found = None
                        for scale in np.linspace(0.5, 1.5, 10):
                            scaled = cv2.resize(logo_cv, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                            sh, sw = scaled.shape[:2]
                            if sw > w or sh > h:
                                continue
                            result_map = cv2.matchTemplate(img, scaled, cv2.TM_CCOEFF_NORMED)
                            _, max_val, _, max_loc = cv2.minMaxLoc(result_map)
                            if found is None or max_val > found[0]:
                                found = (max_val, max_loc, scale)
                        if found and found[0] > 0.3:
                            score = round(found[0], 3)
                            result["checks"].append({
                                "check": "logo_detected",
                                "pass": True,
                                "detail": f"Logo found (match score: {score})",
                            })
                        else:
                            score = round(found[0], 3) if found else 0
                            result["checks"].append({
                                "check": "logo_detected",
                                "pass": False,
                                "detail": f"Logo NOT detected (best match: {score})",
                            })
                            result["pass"] = False

        # --- Brand colour analysis ---
        if campaign.brand_color:
            hex_col = campaign.brand_color.lstrip("#")
            expected_rgb = tuple(int(hex_col[i : i + 2], 16) for i in (0, 2, 4))
            expected_bgr = (expected_rgb[2], expected_rgb[1], expected_rgb[0])

            # Quantize to 32-colour palette for dominant colour analysis
            pil_img = Image.open(image_path).convert("RGB")
            reduced = pil_img.quantize(colors=32).convert("RGB")
            reduced_cv = _pil_to_cv2(reduced)

            pixels = reduced_cv.reshape(-1, 3)
            unique, counts = np.unique(pixels, axis=0, return_counts=True)
            sorted_idx = np.argsort(-counts)
            top_colors = unique[sorted_idx][:5]

            # Check if brand colour is among dominant colours (within a threshold)
            brand_found = False
            for col in top_colors:
                dist = np.linalg.norm(col.astype(float) - np.array(expected_bgr, dtype=float))
                if dist < 60:
                    brand_found = True
                    break

            # Also compute colour coverage percentage
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            expected_hsv = cv2.cvtColor(np.uint8([[expected_bgr]]), cv2.COLOR_BGR2HSV)[0][0]
            # Allow ±15 hue tolerance
            lower = np.array([max(0, expected_hsv[0] - 15), 30, 30])
            upper = np.array([min(179, expected_hsv[0] + 15), 255, 255])
            mask = cv2.inRange(hsv, lower, upper)
            coverage = (cv2.countNonZero(mask) / (w * h)) * 100

            result["checks"].append({
                "check": "brand_color",
                "pass": brand_found or coverage > 1.0,
                "detail": (
                    f"Brand colour {campaign.brand_color} "
                    f"{'found' if brand_found else 'not found in top 5 colours'} "
                    f"(coverage: {coverage:.1f}%)"
                ),
            })

    except Exception as e:
        result["pass"] = False
        result["checks"].append({"check": "error", "pass": False, "detail": str(e)})

    return result


# ---------------------------------------------------------------------------
# 3. Text visibility & clipping check (OpenCV)
# ---------------------------------------------------------------------------
def check_text_visibility(image_path: Path) -> Dict[str, Any]:
    """
    Text visibility checks:
      - Overlay luminance for contrast
      - Top text region not clipped
      - Bottom text region not clipped
    """
    result = {"path": str(image_path), "pass": True, "checks": []}
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError("Could not read image")
        h, w = img.shape[:2]

        # --- Overlay region brightness ---
        bar_height = int(h * 0.35)
        overlay_region = img[h - bar_height : h, :]
        gray_overlay = cv2.cvtColor(overlay_region, cv2.COLOR_BGR2GRAY)
        avg_luminance = np.mean(gray_overlay)

        if avg_luminance < 30:
            result["checks"].append({
                "check": "overlay_too_dark",
                "pass": False,
                "detail": f"Overlay luminance {avg_luminance:.1f} — text may not contrast",
            })
            result["pass"] = False
        elif avg_luminance > 230:
            result["checks"].append({
                "check": "overlay_too_bright",
                "pass": False,
                "detail": f"Overlay luminance {avg_luminance:.1f} — text may wash out",
            })
            result["pass"] = False
        else:
            result["checks"].append({
                "check": "overlay_luminance",
                "pass": True,
                "detail": f"Overlay luminance {avg_luminance:.1f} — good contrast range",
            })

        # --- Top text area — check for clipping (all-white or all-black strip) ---
        top_strip = img[0 : int(h * 0.08), :]
        gray_top = cv2.cvtColor(top_strip, cv2.COLOR_BGR2GRAY)
        top_avg = np.mean(gray_top)
        top_std = np.std(gray_top)
        if top_avg < 10 or top_avg > 250 or top_std < 5:
            result["checks"].append({
                "check": "top_text_area",
                "pass": False,
                "detail": f"Top text area suspicious (avg={top_avg:.1f}, std={top_std:.1f}) — may be clipped",
            })
            result["pass"] = False
        else:
            result["checks"].append({
                "check": "top_text_area",
                "pass": True,
                "detail": f"Top text area ok (avg={top_avg:.1f})",
            })

        # --- Bottom edge — check last rows aren't pure black/white ---
        bottom_strip = img[h - 5 : h, :]
        gray_bottom = cv2.cvtColor(bottom_strip, cv2.COLOR_BGR2GRAY)
        bottom_avg = np.mean(gray_bottom)
        if bottom_avg < 5 or bottom_avg > 250:
            result["checks"].append({
                "check": "bottom_clipping",
                "pass": False,
                "detail": f"Bottom edge clipped (avg={bottom_avg:.1f})",
            })
            result["pass"] = False

    except Exception as e:
        result["pass"] = False
        result["checks"].append({"check": "error", "pass": False, "detail": str(e)})
    return result


# ---------------------------------------------------------------------------
# 4. Image quality checks (OpenCV)
# ---------------------------------------------------------------------------
def check_image_quality(image_path: Path) -> Dict[str, Any]:
    """
    Image quality metrics using OpenCV:
      - Blur detection (Laplacian variance)
      - Brightness / contrast
      - Colourfulness
    """
    result = {"path": str(image_path), "pass": True, "checks": []}
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError("Could not read image")
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # --- Blur detection: Laplacian variance ---
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        if laplacian_var < 30:
            result["checks"].append({
                "check": "blur_detection",
                "pass": False,
                "detail": f"Image may be blurry (Laplacian variance: {laplacian_var:.1f}, threshold: 30)",
            })
            result["pass"] = False
        elif laplacian_var < 60:
            result["checks"].append({
                "check": "blur_detection",
                "pass": True,
                "detail": f"Acceptable sharpness (Laplacian variance: {laplacian_var:.1f})",
            })
        else:
            result["checks"].append({
                "check": "blur_detection",
                "pass": True,
                "detail": f"Good sharpness (Laplacian variance: {laplacian_var:.1f})",
            })

        # --- Overall brightness ---
        mean_brightness = np.mean(gray)
        if mean_brightness < 25:
            result["checks"].append({
                "check": "brightness",
                "pass": False,
                "detail": f"Image too dark (mean brightness: {mean_brightness:.1f}/255)",
            })
            result["pass"] = False
        elif mean_brightness > 240:
            result["checks"].append({
                "check": "brightness",
                "pass": False,
                "detail": f"Image too bright (mean brightness: {mean_brightness:.1f}/255)",
            })
            result["pass"] = False
        else:
            result["checks"].append({
                "check": "brightness",
                "pass": True,
                "detail": f"Good brightness (mean: {mean_brightness:.1f}/255)",
            })

        # --- Colourfulness (Hasler & Süsstrunk metric) ---
        b, g, r = cv2.split(img.astype(float))
        rg = r - g
        yb = 0.5 * (r + g) - b
        std_rg = np.std(rg)
        std_yb = np.std(yb)
        mean_rg = np.mean(rg)
        mean_yb = np.mean(yb)
        colourfulness = np.sqrt(std_rg**2 + std_yb**2) + 0.3 * np.sqrt(mean_rg**2 + mean_yb**2)

        if colourfulness < 5:
            result["checks"].append({
                "check": "colourfulness",
                "pass": False,
                "detail": f"Image appears desaturated (colourfulness: {colourfulness:.1f})",
            })
            result["pass"] = False
        else:
            result["checks"].append({
                "check": "colourfulness",
                "pass": True,
                "detail": f"Good colour variety (score: {colourfulness:.1f})",
            })

    except Exception as e:
        result["pass"] = False
        result["checks"].append({"check": "error", "pass": False, "detail": str(e)})
    return result


# ---------------------------------------------------------------------------
# 5. Legal content check
# ---------------------------------------------------------------------------
def check_legal_content(
    product_name: str, product_message: str, campaign_message: str, cta: str
) -> Dict[str, Any]:
    """Flag prohibited words in campaign copy."""
    flags = []
    all_text = f"{campaign_message} {product_message} {cta}".lower()

    for word in PROHIBITED_WORDS:
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        matches = pattern.findall(all_text)
        if matches:
            entry = {"word": word, "found_in": []}
            if pattern.search(campaign_message):
                entry["found_in"].append("campaign_message")
            if pattern.search(product_message):
                entry["found_in"].append("product_message")
            if pattern.search(cta):
                entry["found_in"].append("cta")
            flags.append(entry)

    return {
        "product": product_name,
        "pass": len(flags) == 0,
        "flagged_words": flags,
    }


# ---------------------------------------------------------------------------
# Main validation pipeline
# ---------------------------------------------------------------------------
def run_validation(campaign: Campaign) -> ValidationReport:
    """
    Execute the full QA pipeline on all generated outputs.

    Args:
        campaign: The campaign brief that was used for generation.

    Returns:
        A ``ValidationReport`` with all check results.
    """
    logger.info("Starting QA validation for campaign: %s", campaign.campaign_name)
    report = ValidationReport(campaign.campaign_name)

    images = _find_output_images(campaign)
    report.total_images = len(images)

    if not images:
        report.errors.append("No generated images found in output directory")
        report.summary = {
            "status": "FAILED",
            "total_images": 0,
            "dimension_pass": 0,
            "dimension_fail": 0,
            "brand_pass": 0,
            "brand_fail": 0,
            "text_pass": 0,
            "text_fail": 0,
            "quality_pass": 0,
            "quality_fail": 0,
            "legal_flags": 0,
        }
        return report

    dim_pass = dim_fail = 0
    brand_pass = brand_fail = 0
    text_pass = text_fail = 0
    quality_pass = quality_fail = 0
    legal_flags = 0

    for img_path in images:
        ratio = _infer_ratio_from_path(img_path)

        d = check_dimensions(img_path, ratio)
        report.dimension_checks.append(d)
        (dim_pass if d["pass"] else dim_fail).__add__(1)
        if d["pass"]: dim_pass += 1
        else: dim_fail += 1

        b = check_brand_compliance(img_path, campaign)
        report.brand_checks.append(b)
        if b["pass"]: brand_pass += 1
        else: brand_fail += 1

        t = check_text_visibility(img_path)
        report.text_checks.append(t)
        if t["pass"]: text_pass += 1
        else: text_fail += 1

        q = check_image_quality(img_path)
        report.quality_checks.append(q)
        if q["pass"]: quality_pass += 1
        else: quality_fail += 1

    for product in campaign.products:
        legal = check_legal_content(
            product.name, product.message, campaign.campaign_message, product.cta
        )
        report.legal_flags.append(legal)
        if not legal["pass"]:
            legal_flags += len(legal["flagged_words"])

    report.summary = {
        "status": "PASS" if (dim_fail == 0 and text_fail == 0) else "ISSUES_FOUND",
        "total_images": report.total_images,
        "expected_images": len(campaign.products) * len(ASPECT_RATIOS),
        "dimension_pass": dim_pass,
        "dimension_fail": dim_fail,
        "brand_pass": brand_pass,
        "brand_fail": brand_fail,
        "text_pass": text_pass,
        "text_fail": text_fail,
        "quality_pass": quality_pass,
        "quality_fail": quality_fail,
        "legal_flags": legal_flags,
    }

    logger.info("Validation complete — summary: %s", report.summary)
    return report
