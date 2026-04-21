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
_DOCTYPE_RE = re.compile(r"<!DOCTYPE[^>]*>", re.IGNORECASE)
_OUTER_SVG_RE = re.compile(
    r"<svg(\s[^>]*)?>",
    re.IGNORECASE | re.DOTALL,
)
_CLOSE_SVG_RE = re.compile(r"</svg\s*>", re.IGNORECASE)
# Strips inline style= attributes so CSS fill/stroke can cascade into the symbol.
_STYLE_ATTR_RE = re.compile(r'\s+style="[^"]*"', re.IGNORECASE)
_PATH_D_RE = re.compile(r'<path[^>]+\bd="([^"]*)"', re.IGNORECASE | re.DOTALL)
_NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_LEADING_M_RE = re.compile(
    r"^[Mm]\s*[-+]?(?:\d+\.?\d*|\.\d+)\s+[-+]?(?:\d+\.?\d*|\.\d+)\s*",
    re.DOTALL,
)


def _strip_svg_wrapper(svg_text: str) -> str:
    """Remove XML declaration, DOCTYPE, and outer <svg>…</svg> tags, returning inner content."""
    svg_text = _XML_DECL_RE.sub("", svg_text)
    svg_text = _DOCTYPE_RE.sub("", svg_text).strip()
    # Remove opening <svg ...>
    svg_text = _OUTER_SVG_RE.sub("", svg_text, count=1).strip()
    # Remove closing </svg>
    svg_text = _CLOSE_SVG_RE.sub("", svg_text).strip()
    return svg_text


def _fmt_coord(v: float) -> str:
    """Format a coordinate: drop trailing .0 for whole numbers."""
    return str(int(v)) if v == int(v) else str(v)


def _chain_edge_cuts(svg_inner: str) -> tuple[str, str] | None:
    """Chain edge_cuts segments into a closed SVG path d string + fill-rule.

    kicad-cli exports each line/arc as a separate <path>.  Boards often have
    multiple disconnected closed components (outer boundary, inner cuts, slots).
    We:
      1. Group segments into connected components by endpoint proximity.
      2. Greedily chain each component into a closed subpath.
      3. Bridge small gaps (≤ HEAL_RADIUS) with straight lines.
      4. Return all subpaths combined with fill-rule="evenodd" so inner shapes
         create holes in the fill.

    Returns (d_string, fill_rule) or None if the outline can't be resolved.
    """
    import math as _math
    from collections import defaultdict

    segs = []
    for m in _PATH_D_RE.finditer(svg_inner):
        d = m.group(1).strip()
        nums = _NUM_RE.findall(d)
        if len(nums) < 4:
            continue
        segs.append({
            "s": (float(nums[0]), float(nums[1])),
            "e": (float(nums[-2]), float(nums[-1])),
            "d": d,
        })

    if len(segs) < 3:
        return None

    def _dist(a: tuple, b: tuple) -> float:
        return _math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)

    def _reverse(seg: dict) -> dict:
        d = seg["d"].replace("\n", " ")
        arc_m = re.match(
            r"M\s*([\S]+)\s+([\S]+)\s+A\s*([\S]+)\s+([\S]+)\s+([\S]+)\s+([\S]+)\s+([\S]+)\s+([\S]+)\s+([\S]+)",
            d, re.IGNORECASE,
        )
        if arc_m:
            x1, y1, rx, ry, rot, large, sweep, x2, y2 = arc_m.groups()
            new_sweep = "0" if sweep.strip() == "1" else "1"
            return {
                "s": seg["e"], "e": seg["s"],
                "d": f"M{x2} {y2} A{rx} {ry} {rot} {large} {new_sweep} {x1} {y1}",
            }
        return {
            "s": seg["e"], "e": seg["s"],
            "d": f"M{seg['e'][0]} {seg['e'][1]} L{seg['s'][0]} {seg['s'][1]}",
        }

    # --- connected components via union-find on endpoint proximity ---
    EPS = 0.05  # mm — small float tolerance for endpoint matching
    n = len(segs)
    parent = list(range(n * 2))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(x: int, y: int) -> None:
        parent[_find(x)] = _find(y)

    # Union each segment's own two endpoints so any segment bridging two
    # groups merges those groups transitively.
    for i in range(n):
        _union(2 * i, 2 * i + 1)

    # Union endpoints across segments that are within EPS of each other.
    for i, si in enumerate(segs):
        for j, sj in enumerate(segs):
            if i >= j:
                continue
            for ei, pi in enumerate([si["s"], si["e"]]):
                for ej, pj in enumerate([sj["s"], sj["e"]]):
                    if _dist(pi, pj) < EPS:
                        _union(2 * i + ei, 2 * j + ej)

    comp_map: dict = defaultdict(list)
    for i, seg in enumerate(segs):
        comp_map[_find(2 * i)].append(seg)

    # Drop tiny components (single segments like slot drills) — keep >= 3 segs.
    components = [c for c in comp_map.values() if len(c) >= 3]

    # --- chain each component ---
    HEAL_RADIUS = 2.0  # mm — bridge small gaps with a straight line

    def _chain_component(comp: list) -> str | None:
        remaining = list(comp)
        chain = [remaining.pop(0)]
        while remaining:
            cur = chain[-1]["e"]
            best_i, best_dist, best_rev = 0, float("inf"), False
            for i, seg in enumerate(remaining):
                ds = _dist(cur, seg["s"])
                de = _dist(cur, seg["e"])
                if ds < best_dist:
                    best_dist, best_i, best_rev = ds, i, False
                if de < best_dist:
                    best_dist, best_i, best_rev = de, i, True
            seg = remaining.pop(best_i)
            chain.append(_reverse(seg) if best_rev else seg)

        parts = [chain[0]["d"].replace("\n", " ")]
        for prev, seg in zip(chain, chain[1:]):
            gap = _dist(prev["e"], seg["s"])
            if gap > HEAL_RADIUS:
                return None
            tail = _LEADING_M_RE.sub("", seg["d"].replace("\n", " ")).strip()
            if gap > EPS and tail:
                parts.append(f"L{seg['s'][0]} {seg['s'][1]}")
            if tail:
                parts.append(tail)
        return " ".join(parts) + " Z"

    subpaths = []
    for comp in components:
        path = _chain_component(comp)
        if path is None:
            return None  # a component has an uncloseable gap — fall back
        subpaths.append(path)

    if not subpaths:
        return None
    return (" ".join(subpaths), "evenodd")


def _compose_svg(manifest: Manifest, zip_path: str) -> str:
    """Build a single composite SVG string from all layer SVGs in stacking order."""
    bb = manifest.board_bounds
    # Board-relative viewBox: layers are translated to 0,0=top-left, page frame clipped.
    view_box = "0 0 {} {}".format(_fmt_coord(bb.width), _fmt_coord(bb.height))

    # Translate inner SVG paths from page coords to board-relative (0,0=top-left).
    layer_translate = "translate({:.4f},{:.4f})".format(-bb.x, -bb.y)

    layers_html: list[str] = []

    # Board fill: chain the edge_cuts segments into one closed path so CSS fill
    # follows the exact board outline (including notches/tabs).
    # Falls back to a rounded rect if chaining produces too few segments.
    edge_cuts_filename = manifest.layers.get("edge_cuts")
    board_fill_result = None
    if edge_cuts_filename:
        try:
            raw = get_svg_bytes(zip_path, edge_cuts_filename).decode("utf-8", errors="replace")
            inner = _strip_svg_wrapper(raw)
            board_fill_result = _chain_edge_cuts(inner)
        except Exception:
            pass
    if board_fill_result:
        fill_d, fill_rule = board_fill_result
        layers_html.append(
            f'  <path class="board-fill" transform="{layer_translate}"'
            f' fill-rule="{fill_rule}" d="{fill_d}"/>'
        )
    else:
        layers_html.append(
            '  <rect class="board-fill" x="0" y="0"'
            ' width="{w}" height="{h}" rx="1" ry="1"/>'.format(
                w=_fmt_coord(bb.width), h=_fmt_coord(bb.height)
            )
        )

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
            # --- Visual outline symbol (kicad-cli art, no pointer events) ---
            sym_outline = "fp-sym-" + re.sub(r"[^a-zA-Z0-9_\-]", "_", outline.overlay_svg)
            if sym_outline not in seen_symbols:
                seen_symbols.add(sym_outline)
                try:
                    raw = get_svg_bytes(zip_path, outline.overlay_svg).decode(
                        "utf-8", errors="replace"
                    )
                    inner = _strip_svg_wrapper(raw)
                    vb_w, vb_h = 0.0, 0.0
                    vb_match = _OUTER_SVG_RE.search(raw)
                    if vb_match:
                        m = re.search(r'viewBox="([^"]+)"', vb_match.group(0), re.IGNORECASE)
                        if m:
                            parts = m.group(1).split()
                            if len(parts) == 4:
                                vb_w = float(parts[2])
                                vb_h = float(parts[3])
                    cx = outline.anchor_x if outline.anchor_x is not None else vb_w / 2
                    cy = outline.anchor_y if outline.anchor_y is not None else vb_h / 2
                    centered = '<g transform="translate({:.4f},{:.4f})">{}</g>'.format(
                        -cx, -cy, inner
                    )
                    symbol_defs.append(
                        '<symbol id="{}" overflow="visible">{}</symbol>'.format(
                            sym_outline, centered
                        )
                    )
                except Exception:
                    sym_outline = ""

            # --- Courtyard symbol (style-stripped so CSS fill/stroke cascades in) ---
            sym_cyd = ""
            if outline.courtyard_svg:
                sym_cyd = "fp-cyd-" + re.sub(r"[^a-zA-Z0-9_\-]", "_", outline.courtyard_svg)
                if sym_cyd not in seen_symbols:
                    seen_symbols.add(sym_cyd)
                    try:
                        raw = get_svg_bytes(zip_path, outline.courtyard_svg).decode(
                            "utf-8", errors="replace"
                        )
                        inner = _STYLE_ATTR_RE.sub("", _strip_svg_wrapper(raw))
                        vb_w, vb_h = 0.0, 0.0
                        vb_match = _OUTER_SVG_RE.search(raw)
                        if vb_match:
                            m = re.search(r'viewBox="([^"]+)"', vb_match.group(0), re.IGNORECASE)
                            if m:
                                parts = m.group(1).split()
                                if len(parts) == 4:
                                    vb_w = float(parts[2])
                                    vb_h = float(parts[3])
                        cx = outline.anchor_x if outline.anchor_x is not None else vb_w / 2
                        cy = outline.anchor_y if outline.anchor_y is not None else vb_h / 2
                        centered = '<g transform="translate({:.4f},{:.4f})">{}</g>'.format(
                            -cx, -cy, inner
                        )
                        symbol_defs.append(
                            '<symbol id="{}" overflow="visible">{}</symbol>'.format(
                                sym_cyd, centered
                            )
                        )
                    except Exception:
                        sym_cyd = ""

            transform = "translate({x:.4f},{y:.4f}) rotate({r:.4f})".format(
                x=comp.pos_x, y=comp.pos_y, r=-comp.rotation
            )
            # Pre-installed components get a non-interactive class; interactive
            # components get data-ref so JS can sync with the BOM panel.
            if comp.installed:
                cyd_class = "fp-installed"
                ref_attr = 'data-installed="1"'
                outline_ref_attr = 'data-installed="1"'
            else:
                cyd_class = "fp-overlay"
                ref_attr = 'data-ref="{}"'.format(comp.ref)
                outline_ref_attr = 'data-ref="{}"'.format(comp.ref)

            if sym_outline:
                overlay_shapes.append(
                    '<use class="fp-svg-outline" {ref_attr}'
                    ' href="#{sym}" transform="{t}"/>'.format(
                        ref_attr=outline_ref_attr, sym=sym_outline, t=transform
                    )
                )
            # Courtyard shape carries all interactive CSS state.
            # Falling back to a bbox rect if courtyard SVG is unavailable.
            if sym_cyd:
                overlay_shapes.append(
                    '<use class="{cls}" {ref_attr}'
                    ' href="#{sym}" transform="{t}"/>'.format(
                        cls=cyd_class, ref_attr=ref_attr, sym=sym_cyd, t=transform
                    )
                )
            elif outline.bbox:
                bw = outline.bbox.get("w", 0)
                bh = outline.bbox.get("h", 0)
                ax = outline.anchor_x if outline.anchor_x is not None else bw / 2
                ay = outline.anchor_y if outline.anchor_y is not None else bh / 2
                overlay_shapes.append(
                    '<rect class="{cls}" {ref_attr}'
                    ' x="{bx:.4f}" y="{by:.4f}" width="{bw:.4f}" height="{bh:.4f}"'
                    ' rx="0.2" ry="0.2" transform="{t}"/>'.format(
                        cls=cyd_class, ref_attr=ref_attr,
                        bx=-ax, by=-ay, bw=bw, bh=bh, t=transform
                    )
                )

        elif outline.type == "bbox" and outline.bbox:
            w = outline.bbox.get("w", 0)
            h = outline.bbox.get("h", 0)
            transform = "translate({:.4f},{:.4f}) rotate({:.4f})".format(
                comp.pos_x, comp.pos_y, comp.rotation
            )
            if comp.installed:
                overlay_shapes.append(
                    '<rect class="fp-installed" data-installed="1"'
                    ' x="{x:.4f}" y="{y:.4f}" width="{w:.4f}" height="{h:.4f}"'
                    ' rx="0.2" ry="0.2" transform="{t}"/>'.format(
                        x=-w / 2, y=-h / 2, w=w, h=h, t=transform
                    )
                )
            else:
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
    # Pre-installed components (installed=True) are shown on the board overlay
    # but excluded from the interactive BOM table.
    bom_sorted = sort_bom(
        [c.model_dump() for c in manifest.components if not c.installed]
    )
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
