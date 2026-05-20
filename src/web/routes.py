"""
FastAPI routes for the Creative Automation Pipeline web UI.

Provides endpoints for:
  - Dashboard (upload / select campaign)
  - Upload product images to data/inputs/
  - Assign/change which image goes with each product
  - Trigger generation
  - View generated images
  - Download individual or all creatives
  - QA validation report
"""
from __future__ import annotations

import io
import json
import logging
import time
import zipfile
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import (
    ASPECT_RATIOS,
    INPUT_DIR,
    OUTPUT_DIR,
    SAMPLE_CAMPAIGN_PATH,
    WEB_HOST,
    WEB_PORT,
)
from src.image_processor import generate_all_creatives
from src.models import Campaign
from src.validators import run_validation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Creative Automation Pipeline", version="1.0.0")

# Templates & static
HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))

# Try to mount static; create dir if missing
static_dir = HERE / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

router = APIRouter()

# ---- In-memory state ------------------------------------------------ #
_campaign: Campaign | None = None
_generation_results: Dict | None = None
_validation_report: Dict | None = None

# Persisted alongside outputs so state survives restarts and is shared between
# any process bind-mounting this directory (e.g. local python vs docker).
STATE_FILE = OUTPUT_DIR / ".state.json"


def _save_state() -> None:
    payload = {
        "campaign": _campaign.model_dump() if _campaign else None,
        "generation_results": _generation_results,
        "validation_report": _validation_report,
    }
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(payload, default=str))
    except Exception as e:
        logger.warning("Failed to save state: %s", e)


def _load_state() -> None:
    global _campaign, _generation_results, _validation_report
    if not STATE_FILE.is_file():
        return
    try:
        payload = json.loads(STATE_FILE.read_text())
    except Exception as e:
        logger.warning("Failed to read state file: %s", e)
        return
    try:
        if payload.get("campaign"):
            _campaign = Campaign(**payload["campaign"])
        _generation_results = payload.get("generation_results")
        _validation_report = payload.get("validation_report")
    except Exception as e:
        logger.warning("Failed to hydrate state: %s", e)


_load_state()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _to_rel(path: Path) -> str:
    """Convert an absolute output path to a URL-friendly relative path."""
    try:
        return str(path.relative_to(OUTPUT_DIR))
    except ValueError:
        return path.name


def _get_output_tree() -> List[Dict]:
    """Walk the output directory and build a nested structure for the template."""
    tree: List[Dict] = []
    if not OUTPUT_DIR.is_dir():
        return tree

    for campaign_dir in sorted(OUTPUT_DIR.iterdir()):
        if not campaign_dir.is_dir():
            continue
        products = []
        for product_dir in sorted(campaign_dir.iterdir()):
            if not product_dir.is_dir():
                continue
            ratios = []
            for ratio_dir in sorted(product_dir.iterdir()):
                if not ratio_dir.is_dir():
                    continue
                images = sorted(ratio_dir.iterdir())
                ratios.append({
                    "name": ratio_dir.name.replace("_", ":"),
                    "rel_dir": str(ratio_dir.relative_to(OUTPUT_DIR)),
                    "images": [
                        {
                            "filename": img.name,
                            "rel": _to_rel(img),
                        }
                        for img in images
                    ],
                })
            if ratios:
                products.append({"name": product_dir.name, "ratios": ratios})
        if products:
            tree.append({"name": campaign_dir.name, "products": products})
    return tree


def _list_input_images() -> List[Dict]:
    """List available images in the inputs folder."""
    images = []
    if INPUT_DIR.is_dir():
        for f in sorted(INPUT_DIR.iterdir()):
            if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                images.append({
                    "filename": f.name,
                    "size_kb": f.stat().st_size // 1024,
                    "url": f"/api/inputs/{f.name}",
                })
    return images


def _campaign_dict():
    """Return the campaign as a plain dict, or None."""
    return _campaign.model_dump() if _campaign else None


def _build_context():
    """Build the common template context dict."""
    return {
        "campaign": _campaign_dict(),
        "generation_results": _generation_results,
        "validation_report": _validation_report,
        "output_tree": _get_output_tree(),
        "input_images": _list_input_images(),
        "aspect_ratios": list(ASPECT_RATIOS.keys()),
        "generation_timestamp": int(time.time()),
    }


def _render(request: Request, **extra):
    """Shortcut to render index.html with merged context."""
    ctx = _build_context()
    ctx.update(extra)
    return templates.TemplateResponse(request, "index.html", context=ctx)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Dashboard: shows upload form and existing output tree."""
    return _render(request)


@router.post("/upload", response_class=HTMLResponse)
async def upload_campaign(request: Request, file: UploadFile = File(...)):
    """Upload a campaign JSON brief."""
    global _campaign

    content = await file.read()
    try:
        data = json.loads(content)
        _campaign = Campaign(**data)
        logger.info("Campaign loaded: %s", _campaign.campaign_name)
    except Exception as e:
        raise HTTPException(400, f"Invalid campaign JSON: {e}")

    _save_state()
    return _render(request, message=f"Campaign '{_campaign.campaign_name}' loaded successfully!")


@router.post("/upload-image", response_class=HTMLResponse)
async def upload_product_image(request: Request, file: UploadFile = File(...)):
    """Upload a product image to data/inputs/."""
    suffix = Path(file.filename).suffix.lower() if file.filename else ".png"
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(400, "Only PNG, JPG, JPEG, and WebP images are accepted")

    dest = INPUT_DIR / f"uploaded_{Path(file.filename).stem}{suffix}"
    content = await file.read()
    dest.write_bytes(content)
    logger.info("Image uploaded: %s (%d bytes)", dest.name, len(content))

    return _render(request, message=f"✅ Image '{dest.name}' uploaded! Add it to a product below.")


@router.post("/assign-image", response_class=HTMLResponse)
async def assign_image_to_product(request: Request, product_name: str = Form(...), image_file: str = Form(...)):
    """Assign an uploaded image to a specific product."""
    global _campaign

    if _campaign is None:
        raise HTTPException(400, "No campaign loaded")

    # Find the product
    for p in _campaign.products:
        if p.name == product_name:
            p.image = image_file
            logger.info("Assigned image '%s' to product '%s'", image_file, p.name)
            _save_state()
            return _render(request, message=f"✅ Assigned '{image_file}' to **{p.name}**")

    raise HTTPException(404, f"Product '{product_name}' not found in campaign")


@router.post("/reset", response_class=HTMLResponse)
async def reset_all(request: Request):
    """Reset everything: clear outputs, inputs, and campaign state."""
    global _campaign, _generation_results, _validation_report, _generation_results_raw

    _campaign = None
    _generation_results = None
    _validation_report = None
    _generation_results_raw = None

    try:
        # Clear output dirs
        if OUTPUT_DIR.is_dir():
            for child in OUTPUT_DIR.iterdir():
                if child.is_dir():
                    import shutil
                    shutil.rmtree(child)
        if INPUT_DIR.is_dir():
            for child in INPUT_DIR.iterdir():
                if child.is_file():
                    child.unlink()
        if STATE_FILE.is_file():
            STATE_FILE.unlink()
    except Exception as e:
        logger.warning("Reset cleanup warning: %s", e)

    logger.info("Full reset complete")
    return _render(request, reset_btn=True)


@router.post("/load-sample", response_class=HTMLResponse)
async def load_sample(request: Request):
    """Load the sample campaign brief."""
    global _campaign

    if not SAMPLE_CAMPAIGN_PATH.is_file():
        raise HTTPException(404, "Sample campaign file not found")

    try:
        with open(SAMPLE_CAMPAIGN_PATH) as f:
            data = json.load(f)
        _campaign = Campaign(**data)
        logger.info("Sample campaign loaded: %s", _campaign.campaign_name)
    except Exception as e:
        raise HTTPException(500, f"Failed to load sample campaign: {e}")

    _save_state()
    return _render(request, message=f"Sample campaign '{_campaign.campaign_name}' loaded!")


@router.post("/generate", response_class=HTMLResponse)
async def trigger_generation(request: Request):
    """Run the full creative generation pipeline."""
    global _campaign, _generation_results, _validation_report

    if _campaign is None:
        raise HTTPException(400, "No campaign loaded. Upload or load a sample first.")

    try:
        _generation_results_raw = generate_all_creatives(_campaign)
        _generation_results = {
            pname: {
                rname: [_to_rel(p) for p in paths]
                for rname, paths in ratios.items()
            }
            for pname, ratios in _generation_results_raw.items()
        }

        _validation_report_obj = run_validation(_campaign)
        _validation_report = _validation_report_obj.to_dict()

        logger.info("Generation and validation completed.")
    except Exception as e:
        logger.exception("Generation failed")
        raise HTTPException(500, f"Generation failed: {e}")

    _save_state()
    return _render(request, message="✨ Generation complete! See results below.")


@router.get("/report", response_class=HTMLResponse)
async def view_report(request: Request):
    """View the latest QA validation report."""
    return templates.TemplateResponse(
        request, "report.html",
        context={
            "report": _validation_report,
            "campaign": _campaign_dict(),
        },
    )


@router.get("/outputs/{path:path}")
async def serve_output(path: str):
    """Serve a generated image file with no-cache headers."""
    file_path = OUTPUT_DIR / path
    if not file_path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(
        str(file_path),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/api/inputs/{filename}")
async def serve_input_image(filename: str):
    """Serve an uploaded input image."""
    file_path = INPUT_DIR / filename
    if not file_path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(str(file_path))


@router.get("/download/all")
async def download_all():
    """Download all generated outputs as a ZIP file."""
    if not OUTPUT_DIR.is_dir():
        raise HTTPException(404, "No outputs generated yet")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in OUTPUT_DIR.rglob("*"):
            if f.is_file():
                arcname = str(f.relative_to(OUTPUT_DIR))
                zf.write(f, arcname)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=creatives.zip"},
    )


@router.get("/api/campaign")
async def get_campaign():
    """Return the loaded campaign as JSON."""
    if _campaign is None:
        raise HTTPException(404, "No campaign loaded")
    return _campaign.model_dump()


@router.get("/download/campaign")
async def download_campaign_json():
    """Download the loaded campaign as a JSON file."""
    if _campaign is None:
        raise HTTPException(404, "No campaign loaded")
    from fastapi.responses import JSONResponse
    data = _campaign.model_dump()
    return JSONResponse(
        content=data,
        headers={
            "Content-Disposition": f'attachment; filename="{_campaign.campaign_name.replace(" ", "_")}_brief.json"',
        },
    )


@router.get("/api/outputs")
async def list_outputs():
    """Return the output tree as JSON."""
    return _get_output_tree()


# ---------------------------------------------------------------------------
# Mount router & startup
# ---------------------------------------------------------------------------
app.include_router(router)


def run_web():
    """Start the Uvicorn server (called from main.py)."""
    import uvicorn
    logger.info("Starting web UI at http://%s:%s", WEB_HOST, WEB_PORT)
    uvicorn.run(app, host=WEB_HOST, port=WEB_PORT)
