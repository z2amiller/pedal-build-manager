"""Manifest loader: reads a .manifest.zip, validates JSON Schema, returns Pydantic models."""

from __future__ import annotations

import json
import zipfile
from typing import Any, Optional

import jsonschema
import kicad_pedal_common.schema as schema_pkg
from pydantic import BaseModel
from referencing import Registry, Resource

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ComponentOutline(BaseModel):
    type: str  # "bbox", "polygon", or "svg"
    bbox: Optional[dict[str, Any]] = None  # {w, h} for bbox; {x, y, w, h} for svg
    points: Optional[list[Any]] = None
    overlay_svg: Optional[str] = None  # zip-relative path; present when type=svg
    fab_svg: Optional[str] = None
    courtyard_svg: Optional[str] = None
    anchor_x: Optional[float] = None  # footprint origin x within overlay SVG (mm)
    anchor_y: Optional[float] = None  # footprint origin y within overlay SVG (mm)


class Component(BaseModel):
    ref: str
    value: str
    footprint: str
    description: Optional[str] = None
    notes: Optional[str] = None
    layer: str  # "F" or "B"
    pos_x: float
    pos_y: float
    rotation: float
    do_not_populate: bool = False
    exclude_from_bom: bool = False
    installed: bool = False  # True = pre-installed (exclude_from_bom); non-interactive overlay only
    outline: Optional[ComponentOutline] = None


class BoardBounds(BaseModel):
    x: float
    y: float
    width: float
    height: float


class Manifest(BaseModel):
    schema_version: str
    board_name: str
    display_name: Optional[str] = None
    version: str
    created_at: str
    board_bounds: BoardBounds
    layers: dict[str, str]  # logical name -> svg filename within zip
    components: list[Component]
    has_blurb: bool = False
    drill_holes: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Schema loading helpers
# ---------------------------------------------------------------------------


def _load_schemas() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (top_schema, entry_schema) loaded from the installed package."""
    schema_dir = schema_pkg._SCHEMA_DIR

    import os

    with open(os.path.join(schema_dir, "manifest-v1.schema.json"), encoding="utf-8") as f:
        top_schema = json.load(f)
    with open(os.path.join(schema_dir, "bom-entry.schema.json"), encoding="utf-8") as f:
        entry_schema = json.load(f)
    return top_schema, entry_schema


def _build_registry(entry_schema: dict[str, Any]) -> Registry:
    return Registry().with_resource(
        entry_schema["$id"],
        Resource.from_contents(entry_schema),
    )


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_manifest(zip_path: str) -> Manifest:
    """Load and validate a .manifest.zip, return in-memory Manifest model.

    Raises:
        ValueError: zip is corrupt, missing required files, or fails schema validation.
    """
    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid zip file: {zip_path!r}") from exc
    except FileNotFoundError as exc:
        raise ValueError(f"File not found: {zip_path!r}") from exc

    with zf:
        try:
            raw = zf.read("manifest.json")
        except KeyError as exc:
            raise ValueError("manifest.json not found inside the zip") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"manifest.json is not valid JSON: {exc}") from exc

    top_schema, entry_schema = _load_schemas()
    registry = _build_registry(entry_schema)

    validator = jsonschema.Draft7Validator(top_schema, registry=registry)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        path = ".".join(str(p) for p in first.absolute_path) or "<root>"
        raise ValueError(f"Schema validation failed at {path!r}: {first.message}")

    return Manifest.model_validate(data)


def get_blurb_text(zip_path: str) -> Optional[str]:
    """Return the contents of blurb.md from the zip, or None if absent."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            try:
                return zf.read("blurb.md").decode("utf-8", errors="replace")
            except KeyError:
                return None
    except zipfile.BadZipFile:
        return None


def get_svg_bytes(zip_path: str, svg_filename: str) -> bytes:
    """Read a specific SVG file from the manifest zip by its filename."""
    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid zip file: {zip_path!r}") from exc

    with zf:
        try:
            return zf.read(svg_filename)
        except KeyError as exc:
            raise ValueError(f"{svg_filename!r} not found inside the zip") from exc
