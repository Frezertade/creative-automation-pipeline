# 🎨 Creative Automation Pipeline

> **Proof-of-concept** for automated social ad creative generation from a campaign brief.

Generate on-brand social media creatives (images with text overlays) for multiple products across three aspect ratios — **1:1 Square**, **9:16 Portrait**, and **16:9 Landscape** — with a built-in QA validation pipeline.

---

## 🚀 Quick Start

### 1. Clone & install

```bash
pip install -r requirements.txt
```

> **System dependencies:** The pipeline uses Pillow for image processing. On Ubuntu/Debian you may need:
> ```bash
> sudo apt-get install -y python3-pil python3-pil.imagetk
> ```

### 2. Run — two modes

#### 🖥️ CLI mode

```bash
python main.py --campaign data/sample_campaign.json
```

Output goes to `outputs/{campaign_name}/{product_name}/{ratio}/`.

#### 🌐 Web UI mode

```bash
python main.py --web
# or
uvicorn main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** in your browser to:
- Upload or select a campaign brief
- Trigger generation
- Browse and download creatives
- View a QA validation report

---

## 📂 Project Structure

```
creative-automation-pipeline/
├── main.py                  # Entry point (CLI + Web)
├── requirements.txt         # Python dependencies
├── README.md                # ← You are here
├── data/
│   ├── sample_campaign.json # Sample campaign brief
│   └── inputs/              # Product images go here
├── outputs/                 # Generated creatives (auto-created)
├── src/
│   ├── __init__.py
│   ├── config.py            # Settings, paths, constants
│   ├── models.py            # Pydantic models (Campaign, Product)
│   ├── image_processor.py   # Core generation engine
│   ├── validators.py        # QA validation pipeline
│   └── web/
│       ├── __init__.py
│       ├── routes.py        # FastAPI routes
│       ├── templates/
│       │   ├── index.html   # Dashboard
│       │   └── report.html  # QA report page
│       └── static/
│           └── style.css    # Dark-themed UI
```

---

## 📋 Campaign Brief Format

Supply a JSON file with this structure:

```json
{
  "campaign_name": "Summer Sale 2026",
  "campaign_message": "Summer Sale — Up to 50% Off!",
  "target_region": "North America",
  "target_audience": "Adults 18–45, social media users",
  "brand_color": "#FF6B35",
  "secondary_color": "#004E89",
  "products": [
    {
      "name": "Wireless Headphones",
      "image": "headphones.jpg",
      "message": "Premium Sound, Zero Wires",
      "cta": "Shop Now",
      "features": ["40h battery", "Noise cancelling", "Bluetooth 5.3"]
    }
  ]
}
```

| Field | Required | Description |
|---|---|---|
| `campaign_name` | ✅ | Used for output folder naming |
| `campaign_message` | ✅ | Primary headline, displayed on all creatives |
| `target_region` | ✅ | Market / region |
| `target_audience` | ✅ | Audience description |
| `brand_color` | ❌ | Primary hex colour (e.g. `#FF6B35`). Falls back to blue |
| `secondary_color` | ❌ | Secondary brand colour |
| `logo_path` | ❌ | Logo filename in `data/inputs/` |
| `products` | ✅ | Array of 2+ products (see below) |

**Product fields:**

| Field | Required | Description |
|---|---|---|
| `name` | ✅ | Product name |
| `image` | ❌ | Filename in `data/inputs/`. `null` or missing → GenAI placeholder |
| `message` | ✅ | Product-specific tagline |
| `cta` | ❌ | Call-to-action text (default: "Shop Now") |
| `features` | ❌ | Array of bullet-point features to display on the creative |

---

## 🧠 How It Works

### Image Loading

1. For each product × aspect ratio, the pipeline looks for the image file in `data/inputs/`.
2. **Image found** → loaded, resized with letterbox padding (`object-fit: contain` equivalent). The full image is always visible, with neutral-dark bars filling any extra space.
3. **Image missing** → a dark gradient placeholder with a sparkle icon is generated, labelled *"GenAI Image Generation Placeholder"* — indicating where a real GenAI model would produce the hero image.

### Text Overlay

Every creative includes:

- **Top banner:** Campaign message (subtle, semi-transparent)
- **Bottom overlay:** Semi-transparent coloured bar (uses brand colour)
- **Product name** (uppercase, muted)
- **Product message** (bold, prominent)
- **Feature bullets** (left-aligned)
- **CTA button** (pill-shaped, bordered)

### Output Organisation

```
outputs/
└── Summer_Sale_2026/
    ├── Wireless_Headphones/
    │   ├── 1_1/wireless_headphones_1_1.png
    │   ├── 9_16/wireless_headphones_9_16.png
    │   └── 16_9/wireless_headphones_16_9.png
    └── Smart_Water_Bottle/
        ├── 1_1/smart_water_bottle_1_1.png
        ├── 9_16/smart_water_bottle_9_16.png
        └── 16_9/smart_water_bottle_16_9.png
```

---

## ✅ QA Validation Pipeline

After generation, the pipeline runs automated checks:

| Check | What it does |
|---|---|
| **📐 Dimensions** | Verifies each image matches its expected aspect ratio (1080×1080, 1080×1920, 1920×1080) |
| **🏷️ Brand Compliance** | Checks brand colour is present in the image; notes if logo file exists |
| **👁️ Text Visibility** | Measures overlay luminance for contrast; checks top text area isn't clipped |
| **⚖️ Legal Content** | Flags prohibited advertising words (e.g. "guaranteed", "risk-free", "limited time only") in all copy |

The report is displayed:
- **CLI mode** → printed to stdout
- **Web mode** → click "View QA Report"

---

## 🛠️ Key Design Decisions

| Decision | Rationale |
|---|---|
| **Pillow** for image processing | Zero external API costs; works offline; predictable output |
| **Pydantic v2** for models | Built-in validation ensures malformed campaign briefs are caught early |
| **FastAPI + Jinja2** for web | Minimal overhead, easy deployment, server-side rendering |
| **Placeholder pattern** | Clearly signals "GenAI image goes here" without requiring API keys for the POC |
| **`object-fit: contain` resize** | Full image always visible — no cropping. Neutral-dark bars fill unused space for consistent canvas sizing |
| **Organised by product/ratio** | Mirror of the campaign hierarchy — easy to find assets for localisation or A/B testing |

---

## ☁️ Deployment

### Deploy to Render

1. Push this repo to GitHub.
2. On [Render](https://render.com), create a new **Web Service**.
3. Connect your repo.
4. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Deploy! The web UI will be available at your Render URL.

### Deploy to Railway

1. Push to GitHub.
2. On [Railway](https://railway.app), create a new project from your repo.
3. Railway auto-detects `requirements.txt` and uses `uvicorn main:app`.
4. No additional config needed.

### Deploy to any VPS

```bash
# Install dependencies
pip install -r requirements.txt

# Run with process manager (e.g., supervisor, systemd)
uvicorn main:app --host 0.0.0.0 --port 8000
```

The pipeline stores no database state — it's entirely file-based, making it trivially portable.

---

## 🧪 Running Tests

```bash
# Quick smoke test (CLI)
python main.py --campaign data/sample_campaign.json

# Test with your own images
# Place images in data/inputs/ and reference them in your campaign JSON
```

---

## ⚠️ Assumptions & Limitations

| Assumption / Limitation | Notes |
|---|---|
| **No actual GenAI calls** | Placeholders mark where GenAI images would be injected. A production system would integrate DALL·E, Stable Diffusion, or Midjourney. |
| **English-only text overlay** | Localisation is structural (text lives in campaign JSON) but not translated. A production system could integrate an LLM translation step. |
| **Simple brand compliance** | Colour detection is basic (dominant colours via palette reduction). True logo detection would need object detection (YOLO, etc.). |
| **File-based storage** | Images save to local disk. Production systems would use S3/Azure Blob with CDN. |
| **No auth** | The web UI has no authentication layer. For production, add OAuth or reverse-proxy auth. |
| **Font availability** | Uses DejaVu Sans if available, otherwise PIL default bitmap font. System fonts can vary. |

---

## 📄 License

MIT — for the take-home exercise. Do whatever you like with it.
