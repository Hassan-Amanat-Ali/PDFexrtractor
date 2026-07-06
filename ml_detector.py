"""
Stage 3: YOLOv8 ML object detection for MEP drawings.

Converts each PDF page to a high-resolution image and runs a trained
YOLOv8 model to detect component symbols without relying on text labels.

If no trained model is found the module returns an empty MLResult with
instructions — the rest of the pipeline continues with Stage 1 + 2.

Training guide (offline step, not part of this script):
  1. Label MEP symbol images using Label Studio or Roboflow
     (sets.dxf symbol blocks can be rendered to synthetic training images).
  2. Run:  yolo train model=yolov8n.pt data=mep_dataset.yaml epochs=100
  3. Copy the trained weights (best.pt) to the same folder as this script,
     renamed to: mep_model.pt
"""

import os
import io
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

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
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False


# Path to trained weights — place best.pt here and rename to mep_model.pt
DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'mep_model.pt'
)

CONFIDENCE_THRESHOLD = 0.45   # minimum YOLO confidence to accept a detection

ML_COLOR: Tuple[int, int, int] = (130, 0, 200)   # purple for ML detections

TRAINING_INSTRUCTIONS = """\
Stage 3 — ML Model Not Trained Yet

To enable YOLOv8 detection for unlabelled / scanned drawings:

1. Install ultralytics:
     pip install ultralytics

2. Collect training images:
   • Render MEP drawing PDF pages as PNG (150–200 dpi)
   • OR generate synthetic images from sets.dxf symbol blocks

3. Label your images:
   • Free tool: Label Studio  (labelstud.io)
   • Draw bounding boxes around each MEP symbol
   • Assign class labels: FCU, FD, XTA, HRU, …

4. Train the model:
     yolo train model=yolov8n.pt data=mep_dataset.yaml epochs=100

5. Copy trained weights here:
     {model_path}

Once the file exists, Stage 3 will run automatically on every drawing.
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MLDetection:
    """One bounding-box detection from the YOLO model."""
    component_type: str
    component_id:   str              # synthetic ID e.g. "FCU-ML-p1-1"
    confidence:     float            # 0.0–1.0
    page_num:       int
    # Pixel coordinates in the inference-resolution image
    bbox_px:        Tuple[float, float, float, float]


@dataclass
class MLResult:
    source_file:     str             = ""
    page_count:      int             = 0
    model_path:      Optional[str]   = None
    model_available: bool            = False
    detections:      List[MLDetection]      = field(default_factory=list)
    # Same shape as ExtractionResult.components
    components:      Dict[str, List[str]]   = field(default_factory=dict)
    warnings:        List[str]       = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public: detection entry point
# ---------------------------------------------------------------------------

def detect_components_ml(
    pdf_path: str,
    model_path: str = None,
    inference_dpi: int = 150,
) -> MLResult:
    """
    Stage 3: run YOLOv8 inference on every page of the PDF.

    Returns an MLResult.  If ultralytics or the model file are missing,
    returns an empty result with an informative warning.
    """
    result = MLResult(source_file=os.path.basename(pdf_path))

    if not PYMUPDF_AVAILABLE:
        result.warnings.append(
            "PyMuPDF not available — Stage 3 requires PyMuPDF."
        )
        return result

    if not YOLO_AVAILABLE:
        result.warnings.append(
            "ultralytics package not installed.\n"
            "Run:  pip install ultralytics\n"
            "Then train and place mep_model.pt next to this file."
        )
        return result

    if model_path is None:
        model_path = DEFAULT_MODEL_PATH

    if not os.path.exists(model_path):
        result.warnings.append(
            TRAINING_INSTRUCTIONS.format(model_path=model_path)
        )
        return result

    # ── Load model ──────────────────────────────────────────────────────────
    result.model_path      = model_path
    result.model_available = True
    try:
        model = YOLO(model_path)
    except Exception as exc:
        result.warnings.append(f"Failed to load YOLO model: {exc}")
        result.model_available = False
        return result

    # ── Run inference page by page ──────────────────────────────────────────
    doc = fitz.open(pdf_path)
    result.page_count = doc.page_count
    scale = inference_dpi / 72.0

    from collections import defaultdict
    comp_map: Dict[str, set] = defaultdict(set)
    det_counters: Dict[str, int] = defaultdict(int)

    for pn, page in enumerate(doc):
        pix     = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        pil_img = Image.frombytes(
            "RGB" if pix.alpha == 0 else "RGBA",
            [pix.width, pix.height], pix.samples
        ).convert("RGB")

        yolo_out = model.predict(pil_img, conf=CONFIDENCE_THRESHOLD, verbose=False)

        for det in yolo_out:
            names = det.names
            for box in det.boxes:
                cls_id = int(box.cls[0])
                conf   = float(box.conf[0])
                name   = names.get(cls_id, f"UNK{cls_id}").upper()
                xyxy   = box.xyxy[0].tolist()

                det_counters[name] += 1
                fake_id = f"{name}-ML-p{pn+1}-{det_counters[name]}"

                result.detections.append(MLDetection(
                    component_type=name,
                    component_id=fake_id,
                    confidence=conf,
                    page_num=pn,
                    bbox_px=(xyxy[0], xyxy[1], xyxy[2], xyxy[3]),
                ))
                comp_map[name].add(fake_id)

    doc.close()
    result.components = {k: sorted(v) for k, v in comp_map.items()}
    return result


# ---------------------------------------------------------------------------
# Public: visual map renderer
# ---------------------------------------------------------------------------

def render_ml_map(
    pdf_path: str,
    ml_result: MLResult,
    taxonomy: dict,
    page_num: int = 0,
    render_dpi: int = 100,
    inference_dpi: int = 150,
) -> Optional[Image.Image]:
    """
    Render the PDF page with ML detection bounding boxes overlaid.

    If no model is available, returns the bare page render with a watermark.
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

    if not ml_result.model_available or not ml_result.detections:
        # Add "no model" watermark
        draw = ImageDraw.Draw(img, "RGBA")
        try:
            font = ImageFont.truetype("arial.ttf", 18)
        except Exception:
            font = ImageFont.load_default()
        msg = "Stage 3: No trained model — see warnings panel"
        draw.text((10, 10), msg, fill=(200, 0, 0, 200), font=font)
        return img

    draw = ImageDraw.Draw(img, "RGBA")
    try:
        font_size = max(7, int(render_dpi * 0.085))
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()
        font_size = 8

    # Scale factor: bboxes are in inference_dpi pixel space, need render_dpi
    px_scale = render_dpi / inference_dpi
    r, g, b  = ML_COLOR

    for det in ml_result.detections:
        if det.page_num != page_num:
            continue
        x0 = det.bbox_px[0] * px_scale
        y0 = det.bbox_px[1] * px_scale
        x1 = det.bbox_px[2] * px_scale
        y1 = det.bbox_px[3] * px_scale

        draw.rectangle([x0, y0, x1, y1],
                       fill=(r, g, b, 40), outline=(r, g, b, 220), width=2)
        label = f"{det.component_type} {det.confidence:.0%}"
        draw.text((x0, max(0, y0 - font_size - 1)),
                  label, fill=(r, g, b, 230), font=font)

    _draw_ml_legend(draw, img.size, font, font_size)
    return img


def _draw_ml_legend(draw, size, font, font_size):
    pad = 5
    lx  = 8
    lw  = 200
    lh  = font_size + 2 * pad + 14
    ly  = size[1] - lh - 8

    draw.rectangle([lx, ly, lx + lw, ly + lh],
                   fill=(255, 255, 255, 185), outline=(100, 100, 100, 200))
    draw.text((lx + pad, ly + pad),
              "Stage 3 — YOLOv8 ML Detection", fill=(0, 0, 0), font=font)
    y = ly + pad + font_size + 2
    r, g, b = ML_COLOR
    draw.rectangle([lx + pad, y, lx + pad + 10, y + 10],
                   fill=(r, g, b, 180), outline=(r, g, b))
    draw.text((lx + pad + 14, y),
              "ML-detected symbol", fill=(0, 0, 0), font=font)
