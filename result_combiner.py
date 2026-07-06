"""
Stage 4: Multi-source result combination and confidence scoring.

Merges Stage 1 (text), Stage 2 (vector), Stage 3 (ML) results and assigns
a confidence level to every component type:

  Confirmed   — text label AND vector symbol found (highest confidence)
  Text only   — Stage 1 found it; Stage 2 vector cluster didn't confirm
  Unlabelled  — Stage 2/3 found a symbol; Stage 1 found no text label
  ML only     — Stage 3 only (lowest confidence, needs review)

Discrepancy flag: set when the count reported by different sources differs
by more than 2 — highlights rows that need a human check.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from pdf_parser   import ExtractionResult
    from vector_analyzer import VectorResult
    from ml_detector  import MLResult

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import fitz
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False


# ---------------------------------------------------------------------------
# Confidence constants and colour mapping
# ---------------------------------------------------------------------------

CONFIRMED   = 'Confirmed'     # text + vector agree
TEXT_ONLY   = 'Text only'     # Stage 1 only (no vector symbol matched)
UNLABELLED  = 'Unlabelled'    # Stage 2 / 3 symbol with no text label
ML_ONLY     = 'ML only'       # Stage 3 only

# RGB tuples for map overlays and Excel cell fills
CONFIDENCE_RGB: Dict[str, Tuple[int, int, int]] = {
    CONFIRMED:  (0,  180,   0),    # green
    TEXT_ONLY:  (0,   90, 210),    # blue
    UNLABELLED: (220, 100,   0),   # orange
    ML_ONLY:    (130,   0, 200),   # purple
}

# Hex versions for Excel fills (openpyxl uses 'RRGGBB')
CONFIDENCE_HEX: Dict[str, str] = {
    CONFIRMED:  'C8F0C8',   # light green
    TEXT_ONLY:  'C8DCFF',   # light blue
    UNLABELLED: 'FFE0A0',   # light orange
    ML_ONLY:    'E8C8FF',   # light purple
}

# Threshold: count difference that triggers the discrepancy flag
DISCREPANCY_DELTA = 2


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CombinedComponent:
    component_type: str
    component_ids:  List[str]          # primary ID list (from text, else vector)
    count:          int
    sources:        Set[str]           # subset of {'text', 'vector', 'ml'}
    confidence:     str                # one of the CONFIDENCE_* constants
    discrepancy:    bool = False       # counts differ across sources
    text_count:     int  = 0
    vector_count:   int  = 0
    ml_count:       int  = 0


@dataclass
class CombinedResult:
    source_file:  str                        = ""
    components:   List[CombinedComponent]    = field(default_factory=list)
    # Unlabelled vector clusters not matched to any text label
    unlabelled_cluster_count: int            = 0
    warnings:     List[str]                  = field(default_factory=list)

    @property
    def confirmed_count(self) -> int:
        return sum(c.count for c in self.components if c.confidence == CONFIRMED)

    @property
    def discrepancy_count(self) -> int:
        return sum(1 for c in self.components if c.discrepancy)

    @property
    def total_count(self) -> int:
        return sum(c.count for c in self.components)


# ---------------------------------------------------------------------------
# Public: combination entry point
# ---------------------------------------------------------------------------

def combine_results(
    text_result,    # ExtractionResult
    vector_result,  # VectorResult
    ml_result,      # MLResult
) -> CombinedResult:
    """
    Merge Stage 1 / 2 / 3 results into a CombinedResult with confidence levels.
    Works even if vector_result or ml_result are empty (no model / analysis failed).
    """
    combined = CombinedResult(source_file=text_result.source_file)
    combined.unlabelled_cluster_count = len(vector_result.unlabelled_clusters)

    # Gather all component types across all sources
    all_types: Set[str] = set()
    all_types.update(text_result.components.keys())
    all_types.update(vector_result.components.keys())
    all_types.update(ml_result.components.keys())

    for comp_type in sorted(all_types):
        text_ids   = set(text_result.components.get(comp_type,   []))
        vector_ids = set(vector_result.components.get(comp_type, []))
        ml_ids     = set(ml_result.components.get(comp_type,     []))

        sources: Set[str] = set()
        if text_ids:   sources.add('text')
        if vector_ids: sources.add('vector')
        if ml_ids:     sources.add('ml')

        # Primary IDs: prefer text, fall back to vector, then ML
        primary_ids = sorted(text_ids or vector_ids or ml_ids)
        count = len(primary_ids)

        # Confidence
        if 'text' in sources and 'vector' in sources:
            confidence = CONFIRMED
        elif 'text' in sources:
            confidence = TEXT_ONLY
        elif 'ml' in sources and 'vector' not in sources:
            confidence = ML_ONLY
        else:
            confidence = UNLABELLED   # vector found it but no text

        # Discrepancy: counts from different sources diverge notably
        source_counts = [n for n in [len(text_ids), len(vector_ids), len(ml_ids)] if n > 0]
        discrepancy = (
            (max(source_counts) - min(source_counts)) > DISCREPANCY_DELTA
            if len(source_counts) > 1 else False
        )

        combined.components.append(CombinedComponent(
            component_type=comp_type,
            component_ids=primary_ids,
            count=count,
            sources=sources,
            confidence=confidence,
            discrepancy=discrepancy,
            text_count=len(text_ids),
            vector_count=len(vector_ids),
            ml_count=len(ml_ids),
        ))

    if combined.unlabelled_cluster_count:
        combined.warnings.append(
            f"{combined.unlabelled_cluster_count} unlabelled vector cluster(s) detected "
            "by Stage 2 — may be components missing a text label on the drawing."
        )

    confirmed = sum(1 for c in combined.components if c.confidence == CONFIRMED)
    check     = combined.discrepancy_count
    if check:
        combined.warnings.append(
            f"{check} component type(s) show a count discrepancy between sources "
            "— highlighted in the Combined tab for review."
        )
    return combined


# ---------------------------------------------------------------------------
# Public: combined visual map renderer
# ---------------------------------------------------------------------------

def render_combined_map(
    pdf_path: str,
    text_result,     # ExtractionResult
    vector_result,   # VectorResult
    ml_result,       # MLResult
    combined_result: CombinedResult,
    taxonomy: dict,
    page_num: int = 0,
    render_dpi: int = 100,
) -> Optional[Image.Image]:
    """
    Render a confidence-coded annotation map for Stage 4.

    Colour-coding:
      Green  = Confirmed (text + vector)
      Blue   = Text only
      Orange = Unlabelled vector cluster
      Purple = ML only
      Red outline = Discrepancy (count mismatch)
    """
    if not PYMUPDF_AVAILABLE or not PIL_AVAILABLE:
        return None

    doc = fitz.open(pdf_path)
    if page_num >= doc.page_count:
        page_num = 0
    page  = doc[page_num]
    scale = render_dpi / 72.0
    pix   = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
    doc.close()

    mode = "RGB" if pix.alpha == 0 else "RGBA"
    img  = Image.frombytes(mode, [pix.width, pix.height], pix.samples).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    try:
        font_size = max(7, int(render_dpi * 0.085))
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()
        font_size = 8

    # Map confidence → RGB for each positioned component
    conf_map: Dict[str, str] = {
        c.component_type: c.confidence
        for c in combined_result.components
    }
    discrep_map: Dict[str, bool] = {
        c.component_type: c.discrepancy
        for c in combined_result.components
    }

    # ── Confirmed / text-only components ────────────────────────────────────
    for pc in vector_result.positioned_components:
        if pc.page_num != page_num:
            continue
        confidence = conf_map.get(pc.component_type, TEXT_ONLY)
        r, g, b    = CONFIDENCE_RGB.get(confidence, (100, 100, 100))
        is_disc    = discrep_map.get(pc.component_type, False)

        x0, y0, x1, y1 = [v * scale for v in pc.bbox]
        draw.rectangle(
            [x0 - 2, y0 - 2, x1 + 2, y1 + 2],
            fill=(r, g, b, 55), outline=(r, g, b, 220), width=2
        )
        if is_disc:  # extra red halo for discrepancy
            draw.rectangle(
                [x0 - 5, y0 - 5, x1 + 5, y1 + 5],
                outline=(220, 0, 0, 200), width=2
            )
        draw.text(
            (x0, max(0, y0 - font_size - 1)),
            pc.component_id, fill=(r, g, b, 230), font=font
        )

    # ── Unlabelled vector clusters ───────────────────────────────────────────
    r, g, b = CONFIDENCE_RGB[UNLABELLED]
    for cl in vector_result.unlabelled_clusters:
        if cl.page_num != page_num:
            continue
        x0, y0, x1, y1 = [v * scale for v in cl.bbox]
        draw.rectangle([x0, y0, x1, y1], outline=(r, g, b, 220), width=2)
        draw.text((x0 + 2, y0 + 2), "?", fill=(r, g, b, 230), font=font)

    # ── ML-only detections ───────────────────────────────────────────────────
    if ml_result.model_available:
        from ml_detector import ML_COLOR
        inference_dpi = 150
        px_scale = render_dpi / inference_dpi
        rm, gm, bm = CONFIDENCE_RGB[ML_ONLY]
        for det in ml_result.detections:
            if det.page_num != page_num:
                continue
            # Only draw if NOT already shown by Stage 1/2 text
            if det.component_type in conf_map and 'text' in (
                c.sources for c in combined_result.components
                if c.component_type == det.component_type
            ):
                continue
            x0 = det.bbox_px[0] * px_scale
            y0 = det.bbox_px[1] * px_scale
            x1 = det.bbox_px[2] * px_scale
            y1 = det.bbox_px[3] * px_scale
            draw.rectangle([x0, y0, x1, y1], outline=(rm, gm, bm, 220), width=2)
            draw.text((x0, max(0, y0 - font_size - 1)),
                      f"ML:{det.component_type}", fill=(rm, gm, bm), font=font)

    _draw_combined_legend(draw, img.size, font, font_size)
    return img


def _draw_combined_legend(draw, size, font, font_size):
    entries = [
        ("Confirmed (text + vector)", CONFIDENCE_RGB[CONFIRMED]),
        ("Text only",                 CONFIDENCE_RGB[TEXT_ONLY]),
        ("Unlabelled symbol",         CONFIDENCE_RGB[UNLABELLED]),
        ("ML detected",               CONFIDENCE_RGB[ML_ONLY]),
        ("Discrepancy",               (220, 0, 0)),
    ]
    pad, box_s, line_h = 5, 10, 14
    legend_w = 215
    legend_h = len(entries) * line_h + 2 * pad + font_size + 2
    lx = 8
    ly = size[1] - legend_h - 8

    draw.rectangle([lx, ly, lx + legend_w, ly + legend_h],
                   fill=(255, 255, 255, 185), outline=(100, 100, 100, 200))
    draw.text((lx + pad, ly + pad),
              "Stage 4 — Confidence Legend", fill=(0, 0, 0), font=font)

    for i, (name, (r, g, b)) in enumerate(entries):
        y = ly + pad + font_size + 2 + i * line_h
        draw.rectangle([lx + pad, y, lx + pad + box_s, y + box_s],
                       fill=(r, g, b, 180), outline=(r, g, b))
        draw.text((lx + pad + box_s + 4, y), name, fill=(0, 0, 0), font=font)
