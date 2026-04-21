"""Tests for the manifest loader."""

from __future__ import annotations

import io
import json
import pathlib
import zipfile

import pytest

from app.manifest import Manifest, get_svg_bytes, load_manifest

EXAMPLE_ZIP = "/Users/andrewmiller/Claude/pedal-build/spec/fuzz-face.manifest.zip"


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_load_valid_manifest() -> None:
    manifest = load_manifest(EXAMPLE_ZIP)

    assert isinstance(manifest, Manifest)
    assert manifest.board_name == "fuzz-face"
    assert manifest.version == "1.0.0"
    assert len(manifest.components) == 18

    r_components = [c for c in manifest.components if c.ref.startswith("R")]
    assert len(r_components) > 0, "expected at least one R-group component"

    assert manifest.layers["edge_cuts"] == "svg/edge_cuts.svg"


def test_get_svg_bytes() -> None:
    data = get_svg_bytes(EXAMPLE_ZIP, "svg/edge_cuts.svg")

    assert len(data) > 0
    # Accept UTF-8 BOM, plain XML declaration, or bare <svg tag
    assert data[:3] == b"\xef\xbb\xbf" or data[:5] == b"<?xml" or data[:4] == b"<svg"


# ---------------------------------------------------------------------------
# Error-path tests
# ---------------------------------------------------------------------------


def test_load_corrupt_zip(tmp_path: pathlib.Path) -> None:
    bad_file = tmp_path / "bad.zip"
    bad_file.write_bytes(b"this is not a zip file")

    with pytest.raises(ValueError, match="valid zip"):
        load_manifest(str(bad_file))


def test_load_invalid_schema(tmp_path: pathlib.Path) -> None:
    """A zip whose manifest.json is missing board_name should raise ValueError."""
    # Build a minimal manifest that omits board_name
    data = {
        "schema_version": "1.0",
        "version": "1.0.0",
        "created_at": "2024-01-01T00:00:00Z",
        "board_bounds": {"x": 0, "y": 0, "width": 50, "height": 50},
        "layers": {
            "f_mask": "svg/f_mask.svg",
            "f_paste": "svg/f_paste.svg",
            "edge_cuts": "svg/edge_cuts.svg",
            "f_silks": "svg/f_silks.svg",
        },
        "components": [],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(data))

    zip_path = tmp_path / "invalid.zip"
    zip_path.write_bytes(buf.getvalue())

    with pytest.raises(ValueError, match="board_name"):
        load_manifest(str(zip_path))
