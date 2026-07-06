"""
PDF extraction engine for MEP drawing component identification.
Extracts component IDs, duct sizes, rooms, and notes from AutoCAD-exported PDFs.
Only counts IDs literally present — never fills sequential gaps.

Supported naming conventions:
  Standard dash:   FCU-02-04, MFSD-02-01, XTA-02-7A
  Slash notation:  CT/02/01, EG/02/05, SG/02/01
  Grille ref:      SG-201-A, SG-207-A  (occurrence-counted, not unique)
  CT subtypes:     CTM-01, CTE-02, CTX-01  (no floor digit)
  Sensor grid:     S204, S207  (3-digit, no dashes)
"""

import re
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    import ezdxf
    EZDXF_AVAILABLE = True
except ImportError:
    EZDXF_AVAILABLE = False


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# 1. Standard dash notation with optional letter suffix on sequence
#    e.g. FCU-02-04, MFSD-02-01, XTA-02-7A, XTA-02-7B
COMPONENT_RE = re.compile(r'\b([A-Z]{1,5})-(\d{2})-(\d{1,3}[A-Za-z]?)\b')

# 2. Slash notation  e.g. CT/02/01, EG/02/05, SG/02/01
SLASH_RE = re.compile(r'\b([A-Z]{1,5})/(\d{2})/(\d{2,3})\b')

# 3. Grille reference with 3-digit number + letter suffix
#    e.g. SG-201-A, SG-207-A  — count OCCURRENCES, not unique IDs
GRILLE_REF_RE = re.compile(r'\b([A-Z]{1,3})-(\d{3})-([A-Z])\b')

# 4. CT subtypes: type letters followed by 2-digit number only (no floor)
#    e.g. CTM-01, CTE-02, CTX-01, CTP-01, CTS-01, FG-2A
CT_SUBTYPE_RE = re.compile(r'\b(CT[MEXPS]|FG)-(\d{1,2}[A-Za-z]?)\b')

# 5. Supply diffusers / sensor grid: S + 3 digits  e.g. S204
SUPPLY_SENSOR_RE = re.compile(r'\bS(\d{3})\b')

# 6. Circular duct size: digits followed by Ø  e.g. 200Ø
ROUND_DUCT_RE = re.compile(r'(\d{2,3})Ø')

# 7. Rectangular duct: widthxheight  e.g. 700x300
RECT_DUCT_RE = re.compile(r'(\d{3,4})[xX](\d{3,4})')

# 8. Room codes: two-digit floor . two-digit room  e.g. 02.32, 02.03
ROOM_RE = re.compile(r'\b(\d{2}\.\d{2,3})\b')

# 11. Lift / platform reference  e.g. PL.01, PL.02
LIFT_RE = re.compile(r'\bPL\.(\d{2})\b')

# 9. Drawing number
DRAWING_NUM_RE = re.compile(r'[A-Z]\d{4,6}-[A-Z]-\d{2}-[A-Z]{2,4}-\d{2}(?:[_-][A-Z])?')

# 10. Floor level from text label
FLOOR_LABEL_RE = re.compile(r'(?:Level|Floor|L)\s*0?(\d+)', re.IGNORECASE)

# Whitelist of known MEP component codes — used for standalone bare-code detection.
# Keep in sync with taxonomy.json keys + any confirmed codes from sets.dxf.
KNOWN_COMPONENT_CODES = {
    # HVAC Equipment
    'FCU', 'BCB', 'BS', 'BSB', 'HRU', 'VAV', 'VRV', 'CDU', 'AHU', 'CAHU',
    'CRU', 'SER', 'SERCU', 'MER', 'MERCU', 'EPH', 'RAD',
    'CT', 'CTM', 'CTE', 'CTX', 'CTP', 'CTS',
    'WP', 'WH', 'SAN', 'ZT', 'DSF',
    # Ventilation
    'XTA', 'ATT', 'GEF', 'EF', 'IEF', 'SEF', 'WCEF', 'LCD',
    'SG', 'RG', 'EG', 'LG', 'FG',
    # Fire Safety
    'FD', 'SD', 'FSD', 'MFSD',
    # Controls
    'VCD', 'MCD', 'NR',
    # Controls & Sensors
    'CO2', 'LD', 'SP', 'GD', 'PIR', 'TS',
    # Pipework
    'PO', 'BV',
}

# Prefixes that are NOT equipment
EXCLUDE_PREFIXES = {
    # Multi-word drawing annotations
    'PL', 'EXIT', 'STEP', 'LIFT', 'MEP', 'WC', 'SS', 'RL',
    # Single-letter drawing marks (room, elevation, detail, north, etc.)
    'R', 'T', 'N', 'E', 'D', 'P', 'B', 'L', 'W', 'V', 'G',
}

# Known note keywords
NOTE_KEYWORDS = [
    'SUPPLY AND INSTALL', 'BUILDING CONTROL', 'EXPOSE BRICKWORK',
    'STRUCTURAL', 'SAMPLE TO BE', 'CONFIRM IF', 'ASSUMPTION',
    'NOTE:', 'INSTALL A NEW', 'REMOVE DUE', 'INFILTRATION',
    'COORDINATION', 'IT IS ASSUMED', 'REPLICATE EXISTING',
    'CONDENSATE', 'CORE DRILLED',
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ExtractionResult:
    source_file: str = ""
    drawing_number: str = ""
    floor_level: str = ""
    discipline: str = "Mechanical"
    # Standard components: code -> sorted list of unique IDs
    components: Dict[str, List[str]] = field(default_factory=dict)
    # Grille references: ref (e.g. SG-207-A) -> occurrence count
    grille_refs: Dict[str, int] = field(default_factory=dict)
    round_ducts: List[str] = field(default_factory=list)
    rect_ducts: List[str] = field(default_factory=list)
    rooms: List[str] = field(default_factory=list)
    lifts: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

def extract_from_pdf(pdf_path: str) -> ExtractionResult:
    """Extract component data from an AutoCAD-exported PDF."""
    if not PYMUPDF_AVAILABLE:
        raise ImportError("PyMuPDF is not installed.\nRun:  pip install PyMuPDF")

    result = ExtractionResult(source_file=os.path.basename(pdf_path))

    doc = fitz.open(pdf_path)
    all_text = ""
    for page in doc:
        all_text += page.get_text()
    doc.close()

    if not all_text.strip():
        result.warnings.append(
            "No text could be extracted from this PDF. "
            "It may be a raster/scanned file — OCR would be needed."
        )
        return result

    _parse_text(all_text, result)
    return result


# ---------------------------------------------------------------------------
# DXF extraction (requires DXF export from AutoCAD, not binary DWG)
# ---------------------------------------------------------------------------

def extract_from_dxf(dxf_path: str) -> ExtractionResult:
    """Extract component data from an AutoCAD DXF file."""
    if not EZDXF_AVAILABLE:
        raise ImportError("ezdxf is not installed.\nRun:  pip install ezdxf")

    result = ExtractionResult(source_file=os.path.basename(dxf_path))
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    components: Dict[str, set] = defaultdict(set)
    text_lines = []

    for entity in msp:
        etype = entity.dxftype()
        if etype == 'INSERT':
            block_name = entity.dxf.name.upper()
            if entity.has_attribs:
                for attrib in entity.attribs:
                    value = attrib.dxf.text.strip().upper()
                    m = COMPONENT_RE.match(value) or SLASH_RE.match(value)
                    if m and m.group(1) not in EXCLUDE_PREFIXES:
                        components[m.group(1)].add(value)
            m = COMPONENT_RE.match(block_name)
            if m and m.group(1) not in EXCLUDE_PREFIXES:
                components[m.group(1)].add(block_name)
        elif etype in ('TEXT', 'MTEXT'):
            text = entity.dxf.text.strip() if etype == 'TEXT' else entity.text.strip()
            text_lines.append(text)

    combined = '\n'.join(text_lines)
    _parse_text(combined, result)

    for code, ids in components.items():
        existing = set(result.components.get(code, []))
        result.components[code] = sorted(existing | ids)

    return result


# ---------------------------------------------------------------------------
# Shared text parsing
# ---------------------------------------------------------------------------

def _parse_text(text: str, result: ExtractionResult) -> None:
    """Parse raw text into ExtractionResult fields."""

    # Drawing number
    dn = DRAWING_NUM_RE.search(text)
    if dn:
        result.drawing_number = dn.group(0)

    # Floor level
    fl = FLOOR_LABEL_RE.search(text)
    if fl:
        result.floor_level = f"Level {fl.group(1)}"
    else:
        cm = COMPONENT_RE.search(text) or SLASH_RE.search(text)
        if cm:
            result.floor_level = f"Level {cm.group(2)}"

    components: Dict[str, set] = defaultdict(set)

    # 1. Standard dash notation (FCU-02-04, XTA-02-7A, C-02-01)
    for m in COMPONENT_RE.finditer(text):
        prefix = m.group(1)
        full_id = m.group(0)
        if prefix not in EXCLUDE_PREFIXES:
            components[prefix].add(full_id)

    # 2. Slash notation (CT/02/01, EG/02/05) — normalise to dash form
    for m in SLASH_RE.finditer(text):
        prefix = m.group(1)
        if prefix not in EXCLUDE_PREFIXES and len(prefix) > 1:
            dash_id = f"{prefix}-{m.group(2)}-{m.group(3)}"
            components[prefix].add(dash_id)

    # 3. CT subtypes without floor (CTM-01, FG-2A)
    for m in CT_SUBTYPE_RE.finditer(text):
        prefix = m.group(1)
        full_id = f"{prefix}-{m.group(2)}"
        components[prefix].add(full_id)

    # 4. Supply/sensor grid (S204, S207)
    supply_sensor: set = set()
    for m in SUPPLY_SENSOR_RE.finditer(text):
        supply_sensor.add(f"S{m.group(1)}")
    if supply_sensor:
        components['S'] = components.get('S', set()) | supply_sensor

    # 5. Standalone bare codes — e.g. a component labelled just "PIR" or "FD" with no ID number.
    #    Each occurrence is counted separately: two bare "PIR" texts → PIR-??-1, PIR-??-2.
    #    Only codes in the taxonomy whitelist are accepted (blocks room labels like ROOM, RACK).
    bare_counts: Dict[str, int] = defaultdict(int)
    for line in text.split('\n'):
        stripped = line.strip()
        if re.fullmatch(r'[A-Z]{2,5}', stripped) and stripped in KNOWN_COMPONENT_CODES:
            bare_counts[stripped] += 1
    for code, count in bare_counts.items():
        existing = components.get(code, set())
        for i in range(1, count + 1):
            # If only one occurrence keep the simpler "CODE-??" label
            placeholder = f"{code}-??-{i}" if count > 1 else f"{code}-??"
            existing.add(placeholder)
        components[code] = existing

    result.components = {k: sorted(v) for k, v in components.items()}

    # 5. Grille references (SG-201-A, SG-207-A) — count occurrences
    grille_counts: Dict[str, int] = defaultdict(int)
    for m in GRILLE_REF_RE.finditer(text):
        ref = m.group(0)
        grille_counts[ref] += 1
    result.grille_refs = dict(sorted(grille_counts.items()))

    # 6. Circular duct sizes
    round_found: set = set()
    for m in ROUND_DUCT_RE.finditer(text):
        val = int(m.group(1))
        if 50 <= val <= 2000:
            round_found.add(f"{val}Ø")
    result.round_ducts = sorted(round_found, key=lambda x: int(x[:-1]))

    # 7. Rectangular duct sizes
    rect_found: set = set()
    for m in RECT_DUCT_RE.finditer(text):
        w, h = int(m.group(1)), int(m.group(2))
        if 50 <= w <= 5000 and 50 <= h <= 5000:
            rect_found.add(f"{w}x{h}")
    result.rect_ducts = sorted(rect_found)

    # 8. Room codes (02.32, 02.03 etc.)
    rooms: set = set()
    for m in ROOM_RE.finditer(text):
        rooms.add(m.group(1))
    result.rooms = sorted(rooms)

    # 10. Lift / platform references
    lifts: set = set()
    for m in LIFT_RE.finditer(text):
        lifts.add(f"PL.{m.group(1)}")
    result.lifts = sorted(lifts)

    # 9. Drawing notes
    notes: List[str] = []
    seen: set = set()
    for line in text.split('\n'):
        stripped = line.strip()
        if len(stripped) < 25:
            continue
        upper = stripped.upper()
        if any(kw in upper for kw in NOTE_KEYWORDS):
            key = stripped[:60]
            if key not in seen:
                seen.add(key)
                notes.append(stripped)
    result.notes = notes


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def total_count(result: ExtractionResult) -> int:
    """Total unique component IDs found (excludes grille occurrence counts)."""
    return sum(len(ids) for ids in result.components.values())


def total_grille_count(result: ExtractionResult) -> int:
    """Total physical grille instances (sum of all occurrence counts)."""
    return sum(result.grille_refs.values())


def components_by_category(result: ExtractionResult, taxonomy: dict) -> Dict[str, list]:
    """Return components grouped by category using the taxonomy dict."""
    grouped: Dict[str, list] = defaultdict(list)

    for code, ids in result.components.items():
        info = taxonomy.get(code, {})
        cat = info.get('category', 'Other')
        grouped[cat].append({
            'code': code,
            'full_name': info.get('full_name', f'Unknown ({code})'),
            'ids': ids,
            'count': len(ids),
            'notes': info.get('notes', ''),
            'is_grille': False,
        })

    # Add grille references as a separate block
    if result.grille_refs:
        # Group by prefix (SG, EG, RG…)
        grille_by_prefix: Dict[str, list] = defaultdict(list)
        for ref, qty in result.grille_refs.items():
            prefix = re.match(r'[A-Z]+', ref).group(0)
            grille_by_prefix[prefix].append((ref, qty))

        for prefix, items in sorted(grille_by_prefix.items()):
            info = taxonomy.get(prefix, {})
            cat = info.get('category', 'Ventilation')
            total_qty = sum(q for _, q in items)
            id_list = [f"{ref} (x{qty})" for ref, qty in sorted(items)]
            grouped[cat].append({
                'code': prefix + '-REF',
                'full_name': info.get('full_name', f'Grille / Diffuser ({prefix})') + ' — Ref Schedule',
                'ids': id_list,
                'count': total_qty,
                'notes': f'{len(items)} unique references, {total_qty} physical units total',
                'is_grille': True,
            })

    for cat in grouped:
        grouped[cat].sort(key=lambda x: x['code'])
    return dict(grouped)
