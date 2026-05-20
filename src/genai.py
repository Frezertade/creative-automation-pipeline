"""
GenAI image generation via OpenAI's gpt-image-1.

Optional dependency: only invoked when OPENAI_API_KEY is set. All failures
fall back silently to the placeholder pipeline so the POC always produces output.
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-image-1"
DEFAULT_SIZE = "1024x1024"


def is_enabled() -> bool:
    """True if a GenAI call should be attempted."""
    return bool(os.environ.get("OPENAI_API_KEY"))


def build_prompt(
    product_name: str,
    product_message: str,  # unused — kept for signature stability
    campaign_message: str,  # unused
    region: str,  # unused
) -> str:
    """Compose a *visual-only* product-photography prompt.

    Deliberately omits taglines, campaign messaging, and market context. Those
    cues bias gpt-image-1 toward rendering ad copy into the image; our overlay
    layer is the single source of truth for marketing text.
    """
    return (
        f"A single {product_name}, isolated product photography. "
        "Clean studio shot on a neutral seamless backdrop. Soft diffused lighting, "
        "subtle shadow, sharp focus, photorealistic, high commercial quality. "
        "Centered composition with generous negative space around the product. "
        "ABSOLUTELY NO text, words, letters, numbers, labels, captions, watermarks, "
        "or typography of any kind anywhere in the image. Product only."
    )


def generate_hero_image(prompt: str, size: str = DEFAULT_SIZE) -> Optional[bytes]:
    """
    Call OpenAI image API and return PNG bytes, or None if disabled / failed.

    Never raises — a failed GenAI call simply means the caller will use the
    placeholder fallback. The error is logged so it's still visible.
    """
    if not is_enabled():
        return None

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package not installed — install it to enable GenAI")
        return None

    try:
        client = OpenAI()
        logger.info("GenAI request (model=%s, size=%s): %s", DEFAULT_MODEL, size, prompt[:120])
        resp = client.images.generate(
            model=DEFAULT_MODEL,
            prompt=prompt,
            size=size,
            n=1,
        )
        b64 = resp.data[0].b64_json
        if not b64:
            logger.warning("GenAI returned no image data")
            return None
        return base64.b64decode(b64)
    except Exception as e:
        logger.warning("GenAI request failed: %s", e)
        return None
