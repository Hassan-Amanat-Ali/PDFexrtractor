"""
Stage 2: PDF vector analysis — symbol recognition and visual map generator.

Three complementary layers:
  A) Text-anchored symbol extraction:
       For each component ID found in the PDF text layer (Stage 1 positions),
       search nearby vector paths to find the ACTUAL symbol bounding box.

  B) DXF fingerprint matching:
       Load all MEP symbol block definitions from sets.dxf, compute scale-invariant
       geometric fingerprints (aspect ratio, curve presence, complexity class).
       Match unassigned vector clusters against these fingerprints.

  C) PDF self-fingerprinting (new):
       Build path-density fingerprints from the PDF's OWN confirmed instances.
       Scans the page for windows matching those fingerprints without a text tag.
       Catches symbols (like ATT) made entirely of tiny 1-5pt paths that the
       normal cluster detector filters out.
"""

import os
import re
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import ezdxf
    EZDXF_AVAILABLE = True
except ImportError:
    EZDXF_AVAILABLE = False


# ---------------------------------------------------------------------------
# Known component codes (kept in sync with pdf_parser.KNOWN_COMPONENT_CODES)
# ---------------------------------------------------------------------------
KNOWN_CODES = {
    'FCU', 'BCB', 'BS', 'BSB', 'HRU', 'VAV', 'VRV', 'CDU', 'AHU', 'CAHU',
    'CRU', 'SER', 'SERCU', 'MER', 'MERCU', 'EPH', 'RAD',
    'CT', 'CTM', 'CTE', 'CTX', 'CTP', 'CTS',
    'WP', 'WH', 'SAN', 'ZT', 'DSF',
    'XTA', 'ATT', 'GEF', 'EF', 'IEF', 'SEF', 'WCEF', 'LCD',
    'SG', 'RG', 'EG', 'LG', 'FG',
    'FD', 'SD', 'FSD', 'MFSD',
    'VCD', 'MCD', 'NR',
    'CO2', 'LD', 'SP', 'GD', 'PIR', 'TS',
    'PO', 'BV',
}

# ---------------------------------------------------------------------------
# Regex patterns (same as pdf_parser but redefined to avoid import cycle)
# ---------------------------------------------------------------------------
_COMP_RE  = re.compile(r'\b([A-Z]{1,5})-(\d{2})-(\d{1,3}[A-Za-z]?)\b')
_SLASH_RE = re.compile(r'\b([A-Z]{1,5})/(\d{2})/(\d{2,3})\b')
_EXCLUDE  = {
    'PL', 'EXIT', 'STEP', 'LIFT', 'MEP', 'WC', 'SS', 'RL',
    'R', 'T', 'N', 'E', 'D', 'P', 'B', 'L', 'W', 'V', 'G',
}

# Regex to match a known code anywhere in a string (for DXF block names)
_CODE_RE = re.compile(
    r'\b(' + '|'.join(re.escape(c) for c in sorted(KNOWN_CODES, key=len, reverse=True)) + r')\b'
)

# Category → RGB colour for map annotations
CATEGORY_RGB: Dict[str, Tuple[int, int, int]] = {
    'HVAC Equipment':     (0,   100, 210),
    'Ventilation':        (0,   160,  55),
    'Fire Safety':        (200,  20,  20),
    'Controls':           (130,   0, 180),
    'Controls & Sensors': (160,  50, 190),
    'Pipework':           (150,  90,   0),
    'Other':              (100, 100, 100),
}
UNLABELLED_RGB:   Tuple[int, int, int] = (220, 110,   0)  # orange
FINGERPRINT_RGB:  Tuple[int, int, int] = (160, 100, 200)  # purple — fingerprint-matched


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SymbolFingerprint:
    """Scale-invariant geometric fingerprint of one DXF block (MEP symbol)."""
    code:          str    # component type: FCU, FD, XTA…
    block_name:    str    # original block name in sets.dxf
    n_lines:       int
    n_circles:     int
    n_arcs:        int
    n_poly:        int    # LWPOLYLINE count
    aspect_ratio:  float  # width / height of block bbox
    has_curves:    bool   # any circles or arcs present
    complexity:    int    # total entity count (lines + circles + arcs + poly)


@dataclass
class PositionedComponent:
    """Component ID found in the PDF text layer, with its drawing coordinates."""
    component_id:   str
    component_type: str
    page_num:       int
    bbox:           Tuple[float, float, float, float]  # text label bbox (x0,y0,x1,y1)
    # Actual symbol body bbox found by vector search (None if no paths nearby)
    symbol_bbox: Optional[Tuple[float, float, float, float]] = None


@dataclass
class SymbolCluster:
    """A merged group of nearby vector paths that likely represents one MEP symbol."""
    page_num:          int
    bbox:              Tuple[float, float, float, float]
    path_count:        int
    has_arcs:          bool    = False   # any curved paths in cluster
    nearby_text:       Optional[str]  = None   # text-assigned component ID
    component_type:    Optional[str]  = None   # type from text
    fingerprint_code:  Optional[str]  = None   # type from DXF fingerprint matching
    fingerprint_score: float          = 0.0    # match confidence 0–1


@dataclass
class VectorResult:
    source_file:           str                       = ""
    page_count:            int                       = 0
    positioned_components: List[PositionedComponent] = field(default_factory=list)
    labelled_clusters:     List[SymbolCluster]        = field(default_factory=list)
    unlabelled_clusters:   List[SymbolCluster]        = field(default_factory=list)
    fingerprints_loaded:   int                       = 0   # DXF fingerprints loaded
    components:            Dict[str, List[str]]      = field(default_factory=dict)
    warnings:              List[str]                 = field(default_factory=list)


# ---------------------------------------------------------------------------
# DXF fingerprint extraction
# ---------------------------------------------------------------------------

def extract_dxf_fingerprints(dxf_path: str) -> List[SymbolFingerprint]:
    """
    Read every block in sets.dxf, compute a geometric fingerprint for any block
    whose name contains a known MEP component code.
    Returns a list of SymbolFingerprint objects (one per block match).
    """
    if not EZDXF_AVAILABLE:
        return []
    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception:
        return []

    fingerprints: List[SymbolFingerprint] = []

    for block in doc.blocks:
        if block.name.startswith('*'):   # skip MODEL_SPACE, PAPER_SPACE etc.
            continue
        m = _CODE_RE.search(block.name.upper())
        if not m:
            continue
        code = m.group(1)

        n_lines = n_circles = n_arcs = n_poly = 0
        xs: List[float] = []
        ys: List[float] = []

        for entity in block:
            et = entity.dxftype()
            try:
                if et == 'LINE':
                    n_lines += 1
                    xs += [entity.dxf.start.x, entity.dxf.end.x]
                    ys += [entity.dxf.start.y, entity.dxf.end.y]
                elif et == 'CIRCLE':
                    n_circles += 1
                    xs.append(entity.dxf.center.x)
                    ys.append(entity.dxf.center.y)
                elif et == 'ARC':
                    n_arcs += 1
                    xs.append(entity.dxf.center.x)
                    ys.append(entity.dxf.center.y)
                elif et == 'LWPOLYLINE':
                    n_poly += 1
                    for pt in entity.get_points():
                        xs.append(pt[0]); ys.append(pt[1])
            except Exception:
                continue

        if not xs:
            continue

        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        aspect = w / h if h > 1e-6 else 1.0
        complexity = n_lines + n_circles + n_arcs + n_poly
        has_curves = (n_circles + n_arcs) > 0

        fingerprints.append(SymbolFingerprint(
            code=code,
            block_name=block.name,
            n_lines=n_lines,
            n_circles=n_circles,
            n_arcs=n_arcs,
            n_poly=n_poly,
            aspect_ratio=round(aspect, 3),
            has_curves=has_curves,
            complexity=complexity,
        ))

    return fingerprints


def _match_cluster_to_fingerprints(
    cluster: SymbolCluster,
    fingerprints: List[SymbolFingerprint],
) -> Tuple[Optional[str], float]:
    """
    Compare a vector cluster against all known DXF fingerprints.
    Returns (component_code, confidence) for the best match, or (None, score)
    if no match exceeds the confidence threshold.
    """
    if not fingerprints:
        return None, 0.0

    w = cluster.bbox[2] - cluster.bbox[0]
    h = cluster.bbox[3] - cluster.bbox[1]
    cl_asp = w / h if h > 0 else 1.0

    best_code:  Optional[str] = None
    best_score: float         = 0.0

    for fp in fingerprints:
        # Scale-invariant feature 1: aspect ratio similarity
        a_ratio = min(cl_asp, fp.aspect_ratio) / max(cl_asp, fp.aspect_ratio, 0.01)
        asp_sim = a_ratio  # 1.0 = perfect match, 0.0 = extreme mismatch

        # Scale-invariant feature 2: curve presence agreement
        curve_sim = 1.0 if cluster.has_arcs == fp.has_curves else 0.35

        # Combined score (aspect ratio is primary discriminator)
        score = asp_sim * 0.65 + curve_sim * 0.35

        if score > best_score:
            best_score = score
            best_code  = fp.code

    # Threshold: require 0.62 confidence minimum to report a match
    if best_score < 0.62:
        return None, best_score

    return best_code, best_score


# ---------------------------------------------------------------------------
# Layer A: text positions with symbol body search
# ---------------------------------------------------------------------------

def _text_positions(page, page_num: int) -> List[PositionedComponent]:
    """Return every component ID found in the page text layer, with its bbox."""
    result: List[PositionedComponent] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                bbox = span["bbox"]
                for m in _COMP_RE.finditer(text):
                    if m.group(1) not in _EXCLUDE:
                        result.append(PositionedComponent(
                            m.group(0), m.group(1), page_num, bbox))
                for m in _SLASH_RE.finditer(text):
                    prefix = m.group(1)
                    if prefix not in _EXCLUDE and len(prefix) > 1:
                        dash_id = f"{prefix}-{m.group(2)}-{m.group(3)}"
                        result.append(PositionedComponent(
                            dash_id, prefix, page_num, bbox))
    return result


def _prefilter_drawings(
    all_drawings: List[dict],
    max_size: float,
) -> List[Tuple[float, float, float, float, bool]]:
    """
    Pre-filter page.get_drawings() to only symbol-sized paths.
    Returns list of (x0, y0, x1, y1, has_curves).
    Drops tiny hatch marks (< 1 pt) and large room outlines (> max_size).
    """
    out: List[Tuple[float, float, float, float, bool]] = []
    for d in all_drawings:
        r = d.get('rect')
        if not r:
            continue
        w = r.x1 - r.x0
        h = r.y1 - r.y0
        if min(w, h) < 1.0 or max(w, h) > max_size:
            continue
        has_c = any(item[0] == 'c' for item in d.get('items', []))
        out.append((r.x0, r.y0, r.x1, r.y1, has_c))
    return out


def _find_symbol_bbox_near_text(
    filtered: List[Tuple[float, float, float, float, bool]],
    tx: float, ty: float,
    radius: float,
) -> Optional[Tuple[float, float, float, float]]:
    """
    Merge all pre-filtered drawing paths within `radius` pts of (tx, ty).
    Returns the merged bbox (x0, y0, x1, y1) representing the symbol body,
    or None if nothing is found.
    """
    candidates: List[Tuple[float, float, float, float]] = []
    # Each individual path must be smaller than 2× the search radius
    max_path = radius * 2.0

    for x0, y0, x1, y1, _ in filtered:
        if max(x1 - x0, y1 - y0) > max_path:
            continue
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        if math.hypot(cx - tx, cy - ty) <= radius:
            candidates.append((x0, y0, x1, y1))

    if not candidates:
        return None

    merged = (
        min(c[0] for c in candidates),
        min(c[1] for c in candidates),
        max(c[2] for c in candidates),
        max(c[3] for c in candidates),
    )

    # Reject if merged result is implausibly large — we grabbed overlapping
    # ductwork / adjacent symbols rather than one clean symbol body.
    max_out = radius * 2.5
    if max(merged[2] - merged[0], merged[3] - merged[1]) > max_out:
        return None

    return merged


# ---------------------------------------------------------------------------
# Layer B: vector cluster detection + fingerprint matching
# ---------------------------------------------------------------------------

def _union_find_merge(
    boxes: List[Tuple[float, float, float, float]],
    margin: float,
) -> List[Tuple[float, float, float, float, int]]:
    """
    Merge bounding boxes within `margin` pts of each other using union-find.
    Returns (x0, y0, x1, y1, count) for each merged group.
    """
    n = len(boxes)
    if n == 0:
        return []

    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        parent[find(i)] = find(j)

    expanded = [
        (b[0] - margin, b[1] - margin, b[2] + margin, b[3] + margin)
        for b in boxes
    ]
    for i in range(n):
        ax0, ay0, ax1, ay1 = expanded[i]
        for j in range(i + 1, n):
            bx0, by0, bx1, by1 = expanded[j]
            if ax0 <= bx1 and bx0 <= ax1 and ay0 <= by1 and by0 <= ay1:
                union(i, j)

    groups: Dict[int, List[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    merged = []
    for grp in groups.values():
        orig = [boxes[i] for i in grp]
        x0 = min(b[0] for b in orig)
        y0 = min(b[1] for b in orig)
        x1 = max(b[2] for b in orig)
        y1 = max(b[3] for b in orig)
        merged.append((x0, y0, x1, y1, len(grp)))
    return merged


def _vector_clusters(
    page,
    page_num: int,
    filtered: List[Tuple[float, float, float, float, bool]],
) -> List[SymbolCluster]:
    """
    Cluster pre-filtered drawing paths into symbol-sized groups.
    Uses the pre-filtered list to avoid re-calling page.get_drawings().
    """
    pw = page.rect.width
    ph = page.rect.height

    # Only paths in the symbol size range (5–9% of page dimension per axis)
    raw_boxes: List[Tuple[float, float, float, float]] = []
    raw_curves: List[bool] = []

    for x0, y0, x1, y1, has_c in filtered:
        w = x1 - x0
        h = y1 - y0
        if w < 5 or h < 5:
            continue
        if w > pw * 0.09 or h > ph * 0.09:
            continue
        raw_boxes.append((x0, y0, x1, y1))
        raw_curves.append(has_c)

    merged = _union_find_merge(raw_boxes, margin=8.0)

    clusters: List[SymbolCluster] = []
    for x0, y0, x1, y1, count in merged:
        w = x1 - x0
        h = y1 - y0
        if w < 8 or h < 8:
            continue
        if w > pw * 0.13 or h > ph * 0.13:
            continue

        # Determine if any constituent path had curves
        has_c = False
        for (bx0, by0, bx1, by1), hc in zip(raw_boxes, raw_curves):
            if bx0 >= x0 - 9 and bx1 <= x1 + 9 and by0 >= y0 - 9 and by1 <= y1 + 9:
                if hc:
                    has_c = True
                    break

        clusters.append(SymbolCluster(page_num, (x0, y0, x1, y1), count, has_arcs=has_c))

    return clusters


def _assign_labels(
    clusters: List[SymbolCluster],
    positioned: List[PositionedComponent],
    max_dist: float = 65.0,
) -> None:
    """Pair each vector cluster with the nearest text-confirmed component (in-place)."""
    used: set = set()
    for cluster in clusters:
        cx = (cluster.bbox[0] + cluster.bbox[2]) / 2
        cy = (cluster.bbox[1] + cluster.bbox[3]) / 2
        best_d, best_i = max_dist, None
        for i, pc in enumerate(positioned):
            if i in used:
                continue
            tx = (pc.bbox[0] + pc.bbox[2]) / 2
            ty = (pc.bbox[1] + pc.bbox[3]) / 2
            d  = math.hypot(cx - tx, cy - ty)
            if d < best_d:
                best_d, best_i = d, i
        if best_i is not None:
            cluster.nearby_text    = positioned[best_i].component_id
            cluster.component_type = positioned[best_i].component_type
            used.add(best_i)


# ---------------------------------------------------------------------------
# Layer C: PDF self-fingerprinting (handles tiny-path symbols like ATT)
# ---------------------------------------------------------------------------

@dataclass
class _SelfFP:
    """Path-density fingerprint built from confirmed PDF instances."""
    code:          str
    density:       float   # paths per sq-pt inside symbol bbox
    curve_ratio:   float   # curved / total paths
    win_w:         float   # typical symbol width (pt)
    win_h:         float   # typical symbol height (pt)
    n_instances:   int


def _build_density_grid(
    all_drawings: List[dict],
    page_w: float,
    page_h: float,
    cell: float = 12.0,
) -> Tuple[List[List[int]], List[List[int]], int, int]:
    """
    Grid of path counts per cell for O(1) window queries.
    g_tot[row][col] = total paths centred in that cell.
    g_cur[row][col] = curved-path count.
    Indexes ALL drawing paths including sub-5pt ones (important for ATT/XTA).
    """
    nc = int(page_w / cell) + 2
    nr = int(page_h / cell) + 2
    g_tot = [[0] * nc for _ in range(nr)]
    g_cur = [[0] * nc for _ in range(nr)]
    for d in all_drawings:
        r = d.get('rect')
        if not r:
            continue
        ci = min(nc - 1, max(0, int((r.x0 + r.x1) / (2 * cell))))
        ri = min(nr - 1, max(0, int((r.y0 + r.y1) / (2 * cell))))
        g_tot[ri][ci] += 1
        if any(item[0] == 'c' for item in d.get('items', [])):
            g_cur[ri][ci] += 1
    return g_tot, g_cur, nr, nc


def _query_win(grid, r0, c0, r1, c1, nr, nc) -> int:
    """Sum grid values in inclusive [r0,r1]×[c0,c1], clamped to grid bounds."""
    r0, r1 = max(0, r0), min(nr - 1, r1)
    c0, c1 = max(0, c0), min(nc - 1, c1)
    if r0 > r1 or c0 > c1:
        return 0
    return sum(grid[r][c] for r in range(r0, r1 + 1) for c in range(c0, c1 + 1))


def _detect_att_xta_bodies(
    all_drawings: List[dict],
    positioned: List[PositionedComponent],
    page_text: List[Tuple[float, float, str]],
    page_num: int,
) -> List[SymbolCluster]:
    """
    Layer C: Detect unlabelled ATT/XTA symbol bodies using their exact DXF geometry.

    ATT (in-duct sound attenuator) — horizontal:
      • Filled outer rectangle (fill present, exactly 6 line items)
        ~17pt wide × ~8pt tall  (width ≥ height × 1.5)
      • Unfilled zigzag polyline (8–13 line items) at same centre, same major dim
      • Two narrow side flanges (~0.6 × 5.6pt)

    XTA (crosstalk attenuator) — vertical:
      • Same structure but rotated 90°  (height ≥ width × 1.5)

    Size range: major dim 10–50pt, minor dim 3–20pt.
    A body is reported as *unlabelled* only if no matching-type text (ATT-xx or
    XTA-xx, or ATTENUATOR / SILENCER legend text) exists within 120pt.
    """
    # Build per-type label position sets from confirmed component IDs
    att_coords = [
        ((pc.bbox[0] + pc.bbox[2]) / 2, (pc.bbox[1] + pc.bbox[3]) / 2)
        for pc in positioned if pc.component_type == 'ATT'
    ]
    xta_coords = [
        ((pc.bbox[0] + pc.bbox[2]) / 2, (pc.bbox[1] + pc.bbox[3]) / 2)
        for pc in positioned if pc.component_type == 'XTA'
    ]
    # Also include any page text mentioning ATT/XTA/ATTENUATOR/CROSSTALK
    # (catches legend entries so they are not re-reported as unlabelled)
    att_text_coords = [
        (tx, ty) for tx, ty, t in page_text
        if 'ATT' in t.upper() or 'ATTEN' in t.upper() or 'SILENCER' in t.upper()
    ]
    xta_text_coords = [
        (tx, ty) for tx, ty, t in page_text
        if 'XTA' in t.upper() or 'CROSSTALK' in t.upper()
    ]
    att_all = att_coords + att_text_coords
    xta_all = xta_coords + xta_text_coords

    def _min_dist(cx: float, cy: float, coords: List[Tuple[float, float]]) -> float:
        if not coords:
            return 999.0
        return min(math.hypot(cx - lx, cy - ly) for lx, ly in coords)

    # --- Step 1: Find filled outer rectangles in the ATT/XTA size range ---
    outer_rects = []
    for d in all_drawings:
        if not d.get('fill'):
            continue
        items = d.get('items', [])
        if len(items) != 6:
            continue
        n_lines = sum(1 for it in items if it[0] == 'l')
        if n_lines < 4:
            continue
        r = d['rect']
        w, h = r.width, r.height
        major, minor = max(w, h), min(w, h)
        # ATT major: 14-25pt; XTA major: 22-30pt (vertical) — combined 14-30pt
        if major < 14 or major > 30:
            continue
        if minor < 5 or minor > 20:
            continue
        if major < minor * 1.5:
            continue  # must be clearly elongated (rules out squares)
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        outer_rects.append((r.x0, r.y0, r.x1, r.y1, w, h, major, cx, cy))

    # --- Step 2: Pair each outer rect with a nearby zigzag ---
    results: List[SymbolCluster] = []
    reported: List[Tuple[float, float]] = []

    for x0, y0, x1, y1, ow, oh, major, cx, cy in outer_rects:
        # Skip if already reported at this location (NMS)
        if any(math.hypot(cx - rx, cy - ry) < 12 for rx, ry in reported):
            continue

        best_n = 0
        for d in all_drawings:
            if d.get('fill'):
                continue  # zigzag polyline is unfilled
            items = d.get('items', [])
            n_l = sum(1 for it in items if it[0] == 'l')
            if n_l < 8 or n_l > 13:
                continue
            r = d['rect']
            zw, zh = r.width, r.height
            zcx = (r.x0 + r.x1) / 2
            zcy = (r.y0 + r.y1) / 2
            if math.hypot(zcx - cx, zcy - cy) > 8:
                continue
            if abs(max(zw, zh) - major) > 6:
                continue
            # Zigzag minor dimension must fit within outer rect (not exceed by >50%)
            if min(zw, zh) > minor * 1.5:
                continue
            if n_l > best_n:
                best_n = n_l

        if best_n < 8:
            continue

        # Classify for reporting — orientation heuristic (can vary by drawing)
        sym_type = 'ATT' if ow >= oh * 1.5 else 'XTA'

        # Filter: any ATT *or* XTA label within 50pt means this body already has a label.
        # Threshold 50pt keeps the pair-gap clear: labelled bodies have labels ≤15pt away;
        # co-located-but-unlabelled ATT near XTA-05-11 is 77pt from that XTA label.
        all_label_dist = _min_dist(cx, cy, att_all + xta_all)
        if all_label_dist <= 50:
            continue

        cl = SymbolCluster(
            page_num          = page_num,
            bbox              = (x0, y0, x1, y1),
            path_count        = best_n,
            nearby_text       = None,
            has_arcs          = False,
            fingerprint_code  = sym_type,
            fingerprint_score = 0.90,
        )
        results.append(cl)
        reported.append((cx, cy))

    return results


# ---------------------------------------------------------------------------
# Public: analysis entry point
# ---------------------------------------------------------------------------

def analyze_pdf_vectors(
    pdf_path: str,
    dxf_path: Optional[str] = None,
) -> VectorResult:
    """
    Stage 2 analysis: combine text-anchored symbol detection with DXF fingerprint
    matching.  Pass dxf_path to enable fingerprint identification of unlabelled symbols.

    Returns a VectorResult ready for rendering or export.
    """
    result = VectorResult(source_file=os.path.basename(pdf_path))

    if not PYMUPDF_AVAILABLE:
        result.warnings.append("PyMuPDF not available — Stage 2 requires PyMuPDF.")
        return result

    # Load DXF fingerprints if available
    fingerprints: List[SymbolFingerprint] = []
    if dxf_path and os.path.isfile(dxf_path):
        fingerprints = extract_dxf_fingerprints(dxf_path)
        result.fingerprints_loaded = len(fingerprints)

    doc = fitz.open(pdf_path)
    result.page_count = doc.page_count
    all_pos: List[PositionedComponent] = []
    all_clusters: List[SymbolCluster]  = []

    for pn, page in enumerate(doc):
        pw = page.rect.width
        ph = page.rect.height

        # Adaptive search radius: 3% of narrower page dimension, clamped 30–100 pt
        search_radius = max(30.0, min(100.0, min(pw, ph) * 0.03))
        # Max symbol size for pre-filtering: 15% of page width
        max_sym_size  = max(pw, ph) * 0.15

        # Fetch drawings ONCE per page
        all_drawings = page.get_drawings()
        filtered     = _prefilter_drawings(all_drawings, max_sym_size)

        # Layer A: text positions + symbol body search
        pos = _text_positions(page, pn)
        for pc in pos:
            tx = (pc.bbox[0] + pc.bbox[2]) / 2
            ty = (pc.bbox[1] + pc.bbox[3]) / 2
            pc.symbol_bbox = _find_symbol_bbox_near_text(filtered, tx, ty, search_radius)

        # Layer B: vector clusters + DXF fingerprint matching
        clusters = _vector_clusters(page, pn, filtered)
        _assign_labels(clusters, pos)

        if fingerprints:
            for cl in clusters:
                if cl.nearby_text is None:
                    code, score = _match_cluster_to_fingerprints(cl, fingerprints)
                    cl.fingerprint_code  = code
                    cl.fingerprint_score = score

        # Layer C: DXF-geometry-guided ATT/XTA body detection
        #  Finds the exact filled-rect + zigzag-polyline structure of ATT and XTA
        #  symbols and reports any instance without a nearby matching text label.
        page_text_all = [
            ((s['bbox'][0] + s['bbox'][2]) / 2,
             (s['bbox'][1] + s['bbox'][3]) / 2,
             s['text'].strip())
            for block in page.get_text("dict")["blocks"]
            if block.get("type") == 0
            for line in block.get("lines", [])
            for s in line.get("spans", [])
            if s['text'].strip()
        ]
        extra = _detect_att_xta_bodies(all_drawings, pos, page_text_all, pn)
        clusters.extend(extra)

        all_pos.extend(pos)
        all_clusters.extend(clusters)

    doc.close()

    result.positioned_components = all_pos
    result.labelled_clusters     = [c for c in all_clusters if c.nearby_text is not None]
    result.unlabelled_clusters   = [c for c in all_clusters if c.nearby_text is None]

    comp_map: Dict[str, set] = defaultdict(set)
    for pc in all_pos:
        comp_map[pc.component_type].add(pc.component_id)
    result.components = {k: sorted(v) for k, v in comp_map.items()}

    # Warnings
    unc = result.unlabelled_clusters
    if unc:
        matched = [c for c in unc if c.fingerprint_code]
        if matched:
            type_counts: Dict[str, int] = defaultdict(int)
            for c in matched:
                type_counts[c.fingerprint_code] += 1
            summary = ', '.join(f'{v}x {k}' for k, v in sorted(type_counts.items()))
            result.warnings.append(
                f"{len(unc)} untagged vector cluster(s) found. "
                f"DXF fingerprint suggests: {summary}."
            )
        else:
            result.warnings.append(
                f"{len(unc)} vector cluster(s) with no text label "
                "(no confident fingerprint match)."
            )

    if result.fingerprints_loaded == 0 and dxf_path:
        result.warnings.append("DXF fingerprint load failed — check sets.dxf is accessible.")

    return result


# ---------------------------------------------------------------------------
# Public: visual map renderer
# ---------------------------------------------------------------------------

def render_page_map(
    pdf_path: str,
    vector_result: VectorResult,
    taxonomy: dict,
    page_num: int = 0,
    dpi: int = 100,
    show_unlabelled: bool = True,
    stage_label: str = "Stage 2",
    extra_overlays: Optional[List[Tuple]] = None,
) -> Optional[Image.Image]:
    """
    Render an annotated PNG map for one page of the PDF.

    Stage 2 visualisation:
      • Colored box at SYMBOL BODY location (from vector search) with component code
      • Dot + connector line to the text label position
      • Orange box = unlabelled cluster with no text; label shows fingerprint suggestion
      • Purple box = fingerprint-only match (no text confirmation)

    extra_overlays: [(x0,y0,x1,y1, page_num, rgb, label), ...] for Stage 4 combined map.
    """
    if not PYMUPDF_AVAILABLE or not PIL_AVAILABLE:
        return None

    doc = fitz.open(pdf_path)
    if page_num >= doc.page_count:
        page_num = 0
    page  = doc[page_num]
    scale = dpi / 72.0
    pix   = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    doc.close()

    mode = "RGB" if pix.alpha == 0 else "RGBA"
    img  = Image.frombytes(mode, [pix.width, pix.height], pix.samples).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    try:
        font_size = max(8, int(dpi * 0.090))
        font      = ImageFont.truetype("arial.ttf", font_size)
        small_font = ImageFont.truetype("arial.ttf", max(7, font_size - 2))
    except Exception:
        font = small_font = ImageFont.load_default()

    MIN_BOX = max(16, int(font_size * 1.8))  # minimum visible box side

    # ── Layer A: text-confirmed component boxes ───────────────────────────────
    for pc in vector_result.positioned_components:
        if pc.page_num != page_num:
            continue
        info    = taxonomy.get(pc.component_type, {})
        cat     = info.get('category', 'Other')
        r, g, b = CATEGORY_RGB.get(cat, CATEGORY_RGB['Other'])

        # Text label centre (tiny — where the text is in the drawing)
        tx = ((pc.bbox[0] + pc.bbox[2]) / 2) * scale
        ty = ((pc.bbox[1] + pc.bbox[3]) / 2) * scale

        if pc.symbol_bbox:
            # Use the actual symbol body bbox (vector-confirmed)
            sx0 = pc.symbol_bbox[0] * scale
            sy0 = pc.symbol_bbox[1] * scale
            sx1 = pc.symbol_bbox[2] * scale
            sy1 = pc.symbol_bbox[3] * scale
            # Ensure minimum visible size
            if sx1 - sx0 < MIN_BOX:
                cx = (sx0 + sx1) / 2
                sx0, sx1 = cx - MIN_BOX/2, cx + MIN_BOX/2
            if sy1 - sy0 < MIN_BOX:
                cy = (sy0 + sy1) / 2
                sy0, sy1 = cy - MIN_BOX/2, cy + MIN_BOX/2

            pad = 4
            # Filled + bordered symbol box
            draw.rectangle([sx0-pad, sy0-pad, sx1+pad, sy1+pad],
                           fill=(r, g, b, 55), outline=(r, g, b, 220), width=2)
            # Component type code inside the box
            cx_ = (sx0 + sx1) / 2
            cy_ = (sy0 + sy1) / 2
            draw.text((cx_ - font_size*0.8, cy_ - font_size/2),
                      pc.component_type, fill=(r, g, b, 240), font=font)
            # Connector line from symbol centre to text tag position
            draw.line([cx_, cy_, tx, ty], fill=(r, g, b, 130), width=1)
            # Small dot at text label
            draw.ellipse([tx-3, ty-3, tx+3, ty+3], fill=(r, g, b, 210))

        else:
            # No symbol body found — draw a marker at the text position
            x0 = pc.bbox[0] * scale;  y0 = pc.bbox[1] * scale
            x1 = pc.bbox[2] * scale;  y1 = pc.bbox[3] * scale
            if x1 - x0 < MIN_BOX:
                cx = (x0 + x1) / 2; x0, x1 = cx - MIN_BOX/2, cx + MIN_BOX/2
            if y1 - y0 < MIN_BOX:
                cy = (y0 + y1) / 2; y0, y1 = cy - MIN_BOX/2, cy + MIN_BOX/2
            pad = 3
            draw.rectangle([x0-pad, y0-pad, x1+pad, y1+pad],
                           fill=(r, g, b, 40), outline=(r, g, b, 180), width=1)
            draw.text((x0, max(0, y0 - font_size - 1)),
                      pc.component_type, fill=(r, g, b, 210), font=font)

    # ── Unlabelled vector clusters ────────────────────────────────────────────
    if show_unlabelled:
        for cl in vector_result.unlabelled_clusters:
            if cl.page_num != page_num:
                continue
            x0, y0, x1, y1 = [v * scale for v in cl.bbox]

            if cl.fingerprint_code:
                # Fingerprint-matched: purple outline, slightly different style
                r, g, b = FINGERPRINT_RGB
                lbl = f"? {cl.fingerprint_code} ({int(cl.fingerprint_score * 100)}%)"
            else:
                # Completely unknown
                r, g, b = UNLABELLED_RGB
                lbl = "? UNKNOWN"

            pad = max(8, font_size)
            bx0, by0 = x0 - pad, y0 - pad
            bx1, by1 = x1 + pad, y1 + pad

            # Outer box
            draw.rectangle([bx0, by0, bx1, by1],
                           fill=(r, g, b, 65), outline=(r, g, b, 240), width=4)
            # Inner dashed-style border
            draw.rectangle([bx0+4, by0+4, bx1-4, by1-4],
                           outline=(255, 240, 0, 170), width=2)
            # Label above the box
            draw.text((bx0, max(0, by0 - font_size - 2)),
                      lbl, fill=(r, g, b, 255), font=small_font)

    # ── Stage 4 extra overlays ────────────────────────────────────────────────
    if extra_overlays:
        for item in extra_overlays:
            if len(item) >= 5 and item[4] != page_num:
                continue
            ox0, oy0, ox1, oy1 = [v * scale for v in item[:4]]
            ir, ig, ib = item[5] if len(item) > 5 else (255, 0, 0)
            lbl2 = item[6] if len(item) > 6 else ""
            draw.rectangle([ox0-4, oy0-4, ox1+4, oy1+4],
                           outline=(ir, ig, ib, 240), width=3)
            if lbl2:
                draw.text((ox0, max(0, oy0 - font_size - 1)),
                          lbl2, fill=(ir, ig, ib, 230), font=font)

    _draw_legend(draw, img.size, font, small_font, font_size, stage_label,
                 has_fingerprint=any(
                     c.fingerprint_code for c in vector_result.unlabelled_clusters
                 ))
    return img


def _draw_legend(draw, size, font, small_font, font_size: int, stage_label: str,
                 has_fingerprint: bool = False):
    """Draw a category legend in the bottom-left corner."""
    entries = list(CATEGORY_RGB.items())
    entries.append(("Symbol (no text label)", UNLABELLED_RGB))
    if has_fingerprint:
        entries.append(("DXF-matched (no text)", FINGERPRINT_RGB))

    pad, box_s, line_h = 5, 10, 15
    legend_w  = 220
    legend_h  = len(entries) * line_h + 2 * pad + font_size + 4
    lx = 8
    ly = size[1] - legend_h - 8

    draw.rectangle([lx, ly, lx + legend_w, ly + legend_h],
                   fill=(255, 255, 255, 190), outline=(80, 80, 80, 200))
    draw.text((lx + pad, ly + pad), stage_label + " — Legend",
              fill=(0, 0, 0), font=font)

    for i, (name, (r, g, b)) in enumerate(entries):
        y = ly + pad + font_size + 4 + i * line_h
        draw.rectangle([lx + pad, y, lx + pad + box_s, y + box_s],
                       fill=(r, g, b, 180), outline=(r, g, b))
        draw.text((lx + pad + box_s + 5, y), name[:28],
                  fill=(0, 0, 0), font=small_font)
