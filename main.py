#!/usr/bin/env python3
"""Creative Automation Pipeline — Entry Point.

Usage:
    # CLI mode — generate from a campaign JSON
    python main.py --campaign data/sample_campaign.json

    # Web mode — launch the FastAPI UI
    python main.py --web

    # Direct uvicorn (for production deployments)
    uvicorn main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path for direct script execution
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import LOG_FORMAT, LOG_LEVEL, SAMPLE_CAMPAIGN_PATH
from src.image_processor import generate_all_creatives
from src.models import Campaign
from src.validators import run_validation

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format=LOG_FORMAT,
)
logger = logging.getLogger("creative-automation")

# Re-export the FastAPI app so `uvicorn main:app` works
from src.web.routes import app  # noqa: E402, F401


def run_cli(campaign_path: str) -> None:
    """Run the pipeline from the command line."""
    path = Path(campaign_path)
    if not path.is_file():
        logger.error("Campaign file not found: %s", path)
        sys.exit(1)

    logger.info("Loading campaign from: %s", path)
    with open(path) as f:
        data = json.load(f)

    campaign = Campaign(**data)
    logger.info("Campaign: %s (%d products)", campaign.campaign_name, len(campaign.products))

    # Generate
    results = generate_all_creatives(campaign)

    print()
    print("=" * 60)
    print("  GENERATION COMPLETE")
    print("=" * 60)
    for product_name, ratios in results.items():
        print(f"\n  📦 {product_name}")
        for ratio_name, paths in ratios.items():
            for p in paths:
                print(f"    📐 {ratio_name:>5} → {p}")
    print()

    # Validate
    report = run_validation(campaign)
    s = report.summary
    print("=" * 60)
    print("  QA VALIDATION REPORT")
    print("=" * 60)
    print(f"  Status:      {'✅ PASS' if s['status'] == 'PASS' else '⚠️  ISSUES'}")
    print(f"  Images:      {s['total_images']} / {s['expected_images']}")
    print(f"  Dimensions:  {s['dimension_pass']}✓ {s['dimension_fail']}✗")
    print(f"  Brand:       {s['brand_pass']}✓ {s['brand_fail']}✗")
    print(f"  Text vis:    {s['text_pass']}✓ {s['text_fail']}✗")
    print(f"  Legal flags: {s['legal_flags']}")
    print()


def run_web() -> None:
    """Start the web UI."""
    import uvicorn
    from src.config import WEB_HOST, WEB_PORT
    logger.info("Starting web UI at http://%s:%s", WEB_HOST, WEB_PORT)
    uvicorn.run(app, host=WEB_HOST, port=WEB_PORT)


def main():
    parser = argparse.ArgumentParser(
        description="Creative Automation Pipeline — generate social ad creatives from a campaign brief"
    )
    parser.add_argument(
        "--campaign", "-c",
        type=str,
        default=None,
        help="Path to a campaign JSON file (CLI mode)",
    )
    parser.add_argument(
        "--web", "-w",
        action="store_true",
        help="Launch the web UI (FastAPI)",
    )

    args = parser.parse_args()

    if args.web:
        run_web()
    elif args.campaign:
        run_cli(args.campaign)
    else:
        # Default: launch web UI
        logger.info("No arguments provided — launching web UI")
        run_web()


if __name__ == "__main__":
    main()
