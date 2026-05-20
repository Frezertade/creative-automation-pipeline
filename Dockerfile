# ---------------------------------------------------------------------------
# Creative Automation Pipeline — Dockerfile
# Multi-stage: lean production image
# ---------------------------------------------------------------------------

# ---- Build stage ----
FROM python:3.12-slim AS builder

WORKDIR /app

# Install system deps for Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo-dev \
    libpng-dev \
    libfreetype6-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ---- Runtime stage ----
FROM python:3.12-slim

WORKDIR /app

# Runtime system deps (fonts for Pillow text rendering)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Ensure local bin is in PATH
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY main.py .
COPY src/ src/
COPY data/ data/
COPY README.md .

# Create outputs and inputs directories
RUN mkdir -p outputs data/inputs

# Expose web port
EXPOSE 8000

# Default: run web server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
