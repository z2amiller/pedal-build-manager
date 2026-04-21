"""Board routes: index and per-board view."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from kicad_pedal_common.bom import BOM_GROUP_ORDER, bom_group, sort_bom

from app import db
from app.manifest import Manifest, get_svg_bytes, load_manifest
from app.storage import BoardStore

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

# ---------------------------------------------------------------------------
# Board store — hard-coded fixture for development/testing.
# Key: (slug, version)  Value: absolute path to .manifest.zip
# ---------------------------------------------------------------------------

BOARD_STORE: dict[tuple[str, str], str] = {
    ("fuzz-face", "1.0.0"): ("/Users/andrewmiller/Claude/pedal-build/spec/fuzz-face.manifest.zip"),
}

# Layer stacking order (bottom → top)
_LAYER_ORDER = ["f_mask", "f_paste", "edge_cuts", "f_silks", "pth_drills"]

_XML_DECL_RE = re.compile(r"<\?xml[^?]*\?>", re.IGNORECASE)
_OUTER_SVG_RE = re.compile(
    r"<svg(\s[^>]*)?>",
    re.IGNORECASE | re.DOTALL,
)
_CLOSE_SVG_RE = re.compile(r"</svg\s*>", re.IGNORECASE)


def _strip_svg_wrapper(svg_text: str) -> str:
    """Remove XML declaration and outer <svg>…</svg> tags, returning inner content."""
    svg_text = _XML_DECL_RE.sub("", svg_text).strip()
    # Remove opening <svg ...>
    svg_text = _OUTER_SVG_RE.sub("", svg_text, count=1).strip()
    # Remove closing </svg>
    svg_text = _CLOSE_SVG_RE.sub("", svg_text).strip()
    return svg_text


def _fmt_coord(v: float) -> str:
    """Format a coordinate: drop trailing .0 for whole numbers."""
    return str(int(v)) if v == int(v) else str(v)


def _compose_svg(manifest: Manifest, zip_path: str) -> str:
    """Build a single composite SVG string from all layer SVGs in stacking order."""
    bb = manifest.board_bounds
    # Board-relative viewBox: layers are translated to 0,0=top-left, page frame clipped.
    view_box = "0 0 {} {}".format(_fmt_coord(bb.width), _fmt_coord(bb.height))

    # Translate inner SVG paths from page coords to board-relative (0,0=top-left).
    layer_translate = "translate({:.4f},{:.4f})".format(-bb.x, -bb.y)

    layers_html: list[str] = []
    for layer_key in _LAYER_ORDER:
        svg_filename = manifest.layers.get(layer_key)
        if svg_filename is None:
            continue
        try:
            raw = get_svg_bytes(zip_path, svg_filename).decode("utf-8", errors="replace")
        except ValueError:
            continue
        inner = _strip_svg_wrapper(raw)
        layers_html.append(
            f'  <g data-layer="{layer_key}" transform="{layer_translate}">\n{inner}\n  </g>'
        )

    inner_html = "\n".join(layers_html)

    # Footprint overlay — SVG symbols + use elements (type=svg) or bbox rects (type=bbox).
    symbol_defs: list[str] = []
    overlay_shapes: list[str] = []
    seen_symbols: set[str] = set()

    for comp in manifest.components:
        if not comp.outline:
            continue

        outline = comp.outline

        if outline.type == "svg" and outline.overlay_svg:
            # Load the per-footprint overlay SVG and emit it as a <symbol>.
            symbol_id = "fp-sym-" + re.sub(r"[^a-zA-Z0-9_\-]", "_", outline.overlay_svg)
            if symbol_id not in seen_symbols:
                seen_symbols.add(symbol_id)
                try:
                    raw = get_svg_bytes(zip_path, outline.overlay_svg).decode(
                        "utf-8", errors="replace"
                    )
                    inner = _strip_svg_wrapper(raw)
                    # Find the viewBox so we can pre-center the symbol.
                    # kicad-cli exports footprint SVGs with the footprint's
                    # origin at approximately (vb_w/2, vb_h/2) — NOT at (0,0).
                    # We wrap the content in a translate(-vb_w/2, -vb_h/2) so
                    # the symbol's (0,0) lands at the footprint anchor, and
                    # the <use> translate(pos_x, pos_y) is then correct.
                    vb_w, vb_h = 0.0, 0.0
                    vb_match = _OUTER_SVG_RE.search(raw)
                    if vb_match:
                        m = re.search(r'viewBox="([^"]+)"', vb_match.group(0), re.IGNORECASE)
                        if m:
                            parts = m.group(1).split()
                            if len(parts) == 4:
                                vb_w = float(parts[2])
                                vb_h = float(parts[3])
                    # Use stored anchor if available; fall back to viewBox centre.
                    cx = outline.anchor_x if outline.anchor_x is not None else vb_w / 2
                    cy = outline.anchor_y if outline.anchor_y is not None else vb_h / 2
                    centered = '<g transform="translate({:.4f},{:.4f})">{}</g>'.format(
                        -cx, -cy, inner
                    )
                    symbol_defs.append(
                        '<symbol id="{}" overflow="visible">{}</symbol>'.format(
                            symbol_id, centered
                        )
                    )
                except Exception:
                    symbol_id = ""

            if symbol_id:
                transform = "translate({x:.4f},{y:.4f}) rotate({r:.4f})".format(
                    x=comp.pos_x, y=comp.pos_y, r=-comp.rotation
                )
                overlay_shapes.append(
                    '<use class="fp-overlay" data-ref="{ref}"'
                    ' href="#{sym}" transform="{t}"/>'.format(
                        ref=comp.ref, sym=symbol_id, t=transform
                    )
                )

            # Bounding-box hit target centered on the footprint anchor.
            # Uses fp-overlay class so JS click handlers fire on the whole area.
            # fill="transparent" (not "none") so the rect captures pointer events.
            if outline.bbox:
                bw = outline.bbox.get("w", 0)
                bh = outline.bbox.get("h", 0)
                ax = outline.anchor_x if outline.anchor_x is not None else bw / 2
                ay = outline.anchor_y if outline.anchor_y is not None else bh / 2
                transform = "translate({x:.4f},{y:.4f}) rotate({r:.4f})".format(
                    x=comp.pos_x, y=comp.pos_y, r=-comp.rotation
                )
                overlay_shapes.append(
                    '<rect class="fp-overlay fp-hit" data-ref="{ref}"'
                    ' x="{bx:.4f}" y="{by:.4f}" width="{bw:.4f}" height="{bh:.4f}"'
                    ' transform="{t}" fill="transparent" stroke="none"/>'.format(
                        ref=comp.ref, bx=-ax, by=-ay, bw=bw, bh=bh, t=transform
                    )
                )

        elif outline.type == "bbox" and outline.bbox:
            w = outline.bbox.get("w", 0)
            h = outline.bbox.get("h", 0)
            transform = "translate({:.4f},{:.4f}) rotate({:.4f})".format(
                comp.pos_x, comp.pos_y, comp.rotation
            )
            overlay_shapes.append(
                '<rect class="fp-overlay" data-ref="{ref}"'
                ' x="{x:.4f}" y="{y:.4f}" width="{w:.4f}" height="{h:.4f}"'
                ' rx="0.2" ry="0.2" transform="{t}"/>'.format(
                    ref=comp.ref, x=-w / 2, y=-h / 2, w=w, h=h, t=transform
                )
            )

    defs_html = "<defs>\n{}\n</defs>".format("\n".join(symbol_defs)) if symbol_defs else ""
    overlay_g = '<g id="fp-overlay-layer">\n' + "\n".join(overlay_shapes) + "\n</g>"

    return (
        f'<svg id="board-svg" xmlns="http://www.w3.org/2000/svg"'
        f' viewBox="{view_box}" width="100%" height="100%"'
        f' overflow="hidden" style="display:block">\n'
        f"{defs_html}\n"
        f"{inner_html}\n"
        f"{overlay_g}\n"
        f"</svg>"
    )


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Index page — lists available boards."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"message": "No boards loaded yet."},
    )


@router.get("/board/{slug}", response_class=RedirectResponse)
async def board_redirect(request: Request, slug: str) -> RedirectResponse:
    conn = request.app.state.db
    version = db.get_default_version(conn, slug)
    if version is None:
        return Response(
            content=f"No versions found for board {slug!r}.",
            status_code=404,
            media_type="text/plain",
        )
    return RedirectResponse(url=f"/board/{slug}/{version}", status_code=302)


@router.get("/board/{slug}/{version}", response_class=HTMLResponse)
async def board_view(request: Request, slug: str, version: str) -> HTMLResponse:
    """Two-panel board view with composited SVG in the right panel."""
    # Prefer on-disk store; fall back to dev fixture for tests
    store = BoardStore()
    on_disk = store.zip_path(slug, version)
    if on_disk.exists():
        zip_path: str = str(on_disk)
    else:
        zip_path = BOARD_STORE.get((slug, version))  # type: ignore[assignment]
    if zip_path is None:
        return Response(
            content=f"Board {slug!r} version {version!r} not found.",
            status_code=404,
            media_type="text/plain",
        )

    try:
        manifest = load_manifest(zip_path)
    except ValueError as exc:
        return Response(
            content=f"Failed to load manifest: {exc}",
            status_code=500,
            media_type="text/plain",
        )

    board_svg = _compose_svg(manifest, zip_path)

    # Build sorted BOM and group it for the template.
    bom_sorted = sort_bom([c.model_dump() for c in manifest.components])
    group_buckets: dict[str, list] = {g: [] for g in BOM_GROUP_ORDER}
    for entry in bom_sorted:
        group_buckets[bom_group(entry["ref"])].append(entry)
    bom_groups = [(name, items) for name, items in group_buckets.items() if items]

    return templates.TemplateResponse(
        request=request,
        name="board.html",
        context={
            "slug": slug,
            "version": version,
            "manifest": manifest,
            "board_svg": board_svg,
            "bom_sorted": bom_sorted,
            "bom_groups": bom_groups,
        },
    )
