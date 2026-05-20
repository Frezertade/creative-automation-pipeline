"""
Pydantic models for Campaign briefs and Products.

Defines the data structures that represent a campaign brief and its products.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Product(BaseModel):
    """A single product within a campaign."""

    name: str = Field(..., description="Product name")
    image: Optional[str] = Field(
        None, description="Filename in data/inputs/ (e.g. 'product1.jpg'). Null = GenAI needed."
    )
    message: str = Field(..., description="Product-specific tagline or offer")
    cta: str = Field(default="Shop Now", description="Call-to-action button text")
    features: List[str] = Field(
        default_factory=list, description="Key product features to display"
    )


class Campaign(BaseModel):
    """Top-level campaign brief."""

    campaign_name: str = Field(..., description="Campaign name (used for folder naming)")
    campaign_message: str = Field(..., description="Primary campaign headline")
    target_region: str = Field(default="Global", description="Target region / market")
    target_audience: str = Field(default="General", description="Target audience description")

    brand_color: Optional[str] = Field(
        None, description="Primary brand hex colour (e.g. '#FF6B35')"
    )
    secondary_color: Optional[str] = Field(
        None, description="Secondary brand hex colour"
    )
    logo_path: Optional[str] = Field(
        None, description="Optional logo filename in data/inputs/"
    )

    products: List[Product] = Field(
        ..., min_length=2, description="At least two products required"
    )
