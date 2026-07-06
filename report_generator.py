"""
Report generator for MEP component extraction results.
Produces:
  - Excel workbook (.xlsx) with 5 sheets
  - Text report (.txt) combining the best elements from all reviewed AI outputs
"""

import os
import sys
import json
from datetime import datetime
from typing import Dict, List


def _resource(filename: str) -> str:
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, filename)

from pdf_parser import ExtractionResult, components_by_category, total_count

try:
    import openpyxl
    from openpyxl.styles import (
        Font, PatternFill, Alignment, Border, Side, numbers
    )
    from openpyxl.utils import get_column_letter
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Category colour palette (Excel fill colours)
# ---------------------------------------------------------------------------
CATEGORY_COLOURS = {
    'HVAC Equipment':      'D6E4F0',   # soft blue
    'Ventilation':         'D5F5E3',   # soft green
    'Fire Safety':         'FADBD8',   # soft red
    'Controls':            'FDEBD0',   # soft orange
    'Controls & Sensors':  'FEF9E7',   # soft yellow
    'Pipework':            'E8DAEF',   # soft purple
    'Heating':             'FDFEFE',   # near white
    'Other':               'F2F3F4',   # light grey
}

HEADER_FILL = 'D3D3D3'  # header row grey
TOTAL_FILL  = 'F0F0F0'


def _load_taxonomy(taxonomy_path: str = None) -> dict:
    if taxonomy_path is None:
        taxonomy_path = _resource('taxonomy.json')
    if os.path.exists(taxonomy_path):
        with open(taxonomy_path, encoding='utf-8') as f:
            return json.load(f)
    return {}


# ---------------------------------------------------------------------------
# Excel report
# ---------------------------------------------------------------------------

def generate_excel(
    result: ExtractionResult,
    output_path: str,
    taxonomy_path: str = None,
    combined_result=None,   # optional result_combiner.CombinedResult
) -> str:
    """
    Generate a .xlsx report with up to 6 sheets:
      1. Equipment Schedule     — detailed per-component table (Stage 1)
      2. Summary                — compact category totals (Stage 1)
      3. Multi-Source Analysis  — Stage 1/2/3/4 combined with confidence (if supplied)
      4. Ductwork               — duct size reference
      5. Spaces Served          — room and lift inventory
      6. Drawing Notes          — annotation text from drawing
    Returns the output_path written.
    """
    if not OPENPYXL_AVAILABLE:
        raise ImportError("openpyxl not installed. Run: pip install openpyxl")

    if taxonomy_path is None:
        taxonomy_path = os.path.join(os.path.dirname(__file__), 'taxonomy.json')
    taxonomy = _load_taxonomy(taxonomy_path)
    grouped  = components_by_category(result, taxonomy)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    _sheet_equipment(wb, result, grouped)
    _sheet_summary(wb, result, grouped)
    if combined_result is not None:
        _sheet_combined(wb, result, combined_result, taxonomy)
    _sheet_ductwork(wb, result)
    _sheet_spaces(wb, result)
    _sheet_notes(wb, result)

    wb.save(output_path)
    return output_path


def _header_style(cell, text, bold=True, fill_hex=HEADER_FILL):
    cell.value = text
    cell.font = Font(bold=bold, name='Calibri', size=10)
    cell.fill = PatternFill('solid', fgColor=fill_hex)
    cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    _border(cell)


def _border(cell, style='thin'):
    s = Side(style=style)
    cell.border = Border(left=s, right=s, top=s, bottom=s)


def _auto_width(ws, min_w=10, max_w=60):
    for col in ws.columns:
        best = min_w
        for cell in col:
            try:
                length = len(str(cell.value or ''))
                if length > best:
                    best = length
            except Exception:
                pass
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(best + 2, max_w)


def _doc_info_rows(ws, result, row=1):
    """Write document information block at top of sheet."""
    info = [
        ('Drawing Number', result.drawing_number or 'N/A'),
        ('Floor / Level',  result.floor_level   or 'N/A'),
        ('Discipline',     result.discipline),
        ('Source File',    result.source_file),
        ('Processed Date', datetime.now().strftime('%Y-%m-%d %H:%M')),
    ]
    for label, value in info:
        ws.cell(row=row, column=1).value = label
        ws.cell(row=row, column=1).font = Font(bold=True, name='Calibri', size=10)
        ws.cell(row=row, column=2).value = value
        ws.cell(row=row, column=2).font = Font(name='Calibri', size=10)
        row += 1
    return row + 1  # blank row after info block


def _sheet_equipment(wb, result: ExtractionResult, grouped: dict):
    ws = wb.create_sheet('Equipment Schedule')
    ws.freeze_panes = 'A8'

    # Title
    ws.merge_cells('A1:I1')
    title_cell = ws['A1']
    title_cell.value = 'MECHANICAL SERVICES — EQUIPMENT SCHEDULE'
    title_cell.font = Font(bold=True, size=13, name='Calibri')
    title_cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 22

    # Document info
    next_row = _doc_info_rows(ws, result, row=2)

    # Table headers
    headers = ['#', 'Category', 'Code', 'Full Name', 'Component IDs', 'Qty',
               'Size / Spec', 'Floor', 'Notes']
    for col, h in enumerate(headers, 1):
        _header_style(ws.cell(row=next_row, column=col), h)
    ws.row_dimensions[next_row].height = 18
    next_row += 1

    row_num = 1
    category_order = [
        'HVAC Equipment', 'Ventilation', 'Fire Safety',
        'Controls & Sensors', 'Controls', 'Pipework', 'Heating', 'Other',
    ]

    for cat in category_order:
        if cat not in grouped:
            continue
        fill_hex = CATEGORY_COLOURS.get(cat, 'FFFFFF')
        fill = PatternFill('solid', fgColor=fill_hex)

        for item in grouped[cat]:
            ids_str = ', '.join(item['ids'])
            # Truncate for display; full list still in the cell via wrap
            r = ws.cell(row=next_row, column=1); r.value = row_num
            r.alignment = Alignment(horizontal='center', vertical='top')
            _border(r)

            for col, val in enumerate([
                cat, item['code'], item['full_name'],
                ids_str, item['count'], '', result.floor_level, item['notes']
            ], 2):
                c = ws.cell(row=next_row, column=col)
                c.value = val
                c.fill = fill
                c.alignment = Alignment(
                    vertical='top',
                    wrap_text=True,
                    horizontal='center' if col in (3, 6, 8) else 'left'
                )
                c.font = Font(name='Calibri', size=10)
                _border(c)

            ws.row_dimensions[next_row].height = max(18, min(len(ids_str) // 6, 60))
            row_num += 1
            next_row += 1

    # Total row
    total = total_count(result)
    ws.cell(row=next_row, column=5).value = 'TOTAL EQUIPMENT'
    ws.cell(row=next_row, column=5).font = Font(bold=True, name='Calibri', size=10)
    ws.cell(row=next_row, column=5).alignment = Alignment(horizontal='right')
    ws.cell(row=next_row, column=6).value = total
    ws.cell(row=next_row, column=6).font = Font(bold=True, name='Calibri', size=11)
    ws.cell(row=next_row, column=6).alignment = Alignment(horizontal='center')
    for col in range(1, 10):
        c = ws.cell(row=next_row, column=col)
        c.fill = PatternFill('solid', fgColor=TOTAL_FILL)
        _border(c)

    _auto_width(ws)
    ws.column_dimensions['E'].width = 55   # IDs column wider
    ws.column_dimensions['D'].width = 30   # Full name


def _sheet_summary(wb, result: ExtractionResult, grouped: dict):
    ws = wb.create_sheet('Summary')

    ws.merge_cells('A1:E1')
    ws['A1'].value = 'COMPONENT SUMMARY'
    ws['A1'].font = Font(bold=True, size=13, name='Calibri')
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 22

    next_row = _doc_info_rows(ws, result, row=2)

    headers = ['Category', 'Code', 'Full Name', 'Count', '% of Total']
    for col, h in enumerate(headers, 1):
        _header_style(ws.cell(row=next_row, column=col), h)
    next_row += 1

    total = total_count(result)
    category_order = [
        'HVAC Equipment', 'Ventilation', 'Fire Safety',
        'Controls & Sensors', 'Controls', 'Pipework', 'Heating', 'Other',
    ]

    cat_subtotals = {}
    for cat in category_order:
        if cat not in grouped:
            continue
        fill_hex = CATEGORY_COLOURS.get(cat, 'FFFFFF')
        fill = PatternFill('solid', fgColor=fill_hex)
        subtotal = 0

        for item in grouped[cat]:
            pct = f"{item['count']/total*100:.1f}%" if total else '0%'
            for col, val in enumerate(
                [cat, item['code'], item['full_name'], item['count'], pct], 1
            ):
                c = ws.cell(row=next_row, column=col)
                c.value = val
                c.fill = fill
                c.font = Font(name='Calibri', size=10)
                c.alignment = Alignment(
                    horizontal='center' if col in (2, 4, 5) else 'left',
                    vertical='center'
                )
                _border(c)
            subtotal += item['count']
            next_row += 1

        cat_subtotals[cat] = subtotal

        # Category subtotal row
        c = ws.cell(row=next_row, column=3)
        c.value = f'{cat} Subtotal'
        c.font = Font(bold=True, name='Calibri', size=10, italic=True)
        c = ws.cell(row=next_row, column=4)
        c.value = subtotal
        c.font = Font(bold=True, name='Calibri', size=10)
        c.alignment = Alignment(horizontal='center')
        for col in range(1, 6):
            ws.cell(row=next_row, column=col).fill = PatternFill('solid', fgColor='E8E8E8')
            _border(ws.cell(row=next_row, column=col))
        next_row += 1

    # Grand total
    next_row += 1
    ws.cell(row=next_row, column=3).value = 'TOTAL EQUIPMENT'
    ws.cell(row=next_row, column=3).font = Font(bold=True, size=12, name='Calibri')
    ws.cell(row=next_row, column=3).alignment = Alignment(horizontal='right')
    ws.cell(row=next_row, column=4).value = total
    ws.cell(row=next_row, column=4).font = Font(bold=True, size=12, name='Calibri')
    ws.cell(row=next_row, column=4).alignment = Alignment(horizontal='center')
    for col in range(1, 6):
        c = ws.cell(row=next_row, column=col)
        c.fill = PatternFill('solid', fgColor='C0C0C0')
        _border(c)

    _auto_width(ws)


def _sheet_ductwork(wb, result: ExtractionResult):
    ws = wb.create_sheet('Ductwork Reference')

    ws['A1'].value = 'DUCTWORK REFERENCE'
    ws['A1'].font = Font(bold=True, size=13, name='Calibri')
    ws['A1'].alignment = Alignment(horizontal='center')
    ws.merge_cells('A1:C1')
    ws.row_dimensions[1].height = 22

    ws['A3'].value = 'Note: Duct sizes are listed as reference only — they are not counted as equipment.'
    ws['A3'].font = Font(italic=True, name='Calibri', size=10)
    ws.merge_cells('A3:C3')

    # Circular
    ws['A5'].value = 'Circular Ductwork'
    ws['A5'].font = Font(bold=True, name='Calibri', size=11)
    _header_style(ws['A6'], 'Size')
    _header_style(ws['B6'], 'Standard Diameter (mm)')
    _header_style(ws['C6'], 'Notes')
    row = 7
    for d in result.round_ducts:
        ws.cell(row=row, column=1).value = d
        ws.cell(row=row, column=2).value = d.replace('Ø', '')
        ws.cell(row=row, column=3).value = 'Circular duct'
        for col in range(1, 4):
            ws.cell(row=row, column=col).font = Font(name='Calibri', size=10)
            _border(ws.cell(row=row, column=col))
        row += 1

    if not result.round_ducts:
        ws.cell(row=row, column=1).value = 'None found'
        row += 1

    # Rectangular
    row += 1
    ws.cell(row=row, column=1).value = 'Rectangular Ductwork'
    ws.cell(row=row, column=1).font = Font(bold=True, name='Calibri', size=11)
    row += 1
    _header_style(ws.cell(row=row, column=1), 'Size')
    _header_style(ws.cell(row=row, column=2), 'Width (mm)')
    _header_style(ws.cell(row=row, column=3), 'Height (mm)')
    row += 1
    for size in result.rect_ducts:
        parts = size.replace('x', 'x').split('x')
        ws.cell(row=row, column=1).value = size
        ws.cell(row=row, column=2).value = parts[0] if len(parts) > 1 else ''
        ws.cell(row=row, column=3).value = parts[1] if len(parts) > 1 else ''
        for col in range(1, 4):
            ws.cell(row=row, column=col).font = Font(name='Calibri', size=10)
            _border(ws.cell(row=row, column=col))
        row += 1

    if not result.rect_ducts:
        ws.cell(row=row, column=1).value = 'None found'

    _auto_width(ws)


def _sheet_spaces(wb, result: ExtractionResult):
    ws = wb.create_sheet('Spaces Served')

    ws['A1'].value = 'SPACES SERVED (context only — not counted in equipment total)'
    ws['A1'].font = Font(bold=True, size=12, name='Calibri')
    ws['A1'].alignment = Alignment(horizontal='center')
    ws.merge_cells('A1:B1')
    ws.row_dimensions[1].height = 20

    row = 3
    if result.rooms:
        _header_style(ws.cell(row=row, column=1), 'Room Code')
        _header_style(ws.cell(row=row, column=2), 'Description')
        row += 1
        for r in result.rooms:
            ws.cell(row=row, column=1).value = r
            ws.cell(row=row, column=2).value = ''
            for col in range(1, 3):
                ws.cell(row=row, column=col).font = Font(name='Calibri', size=10)
                _border(ws.cell(row=row, column=col))
            row += 1

    if result.lifts:
        row += 1
        _header_style(ws.cell(row=row, column=1), 'Lift / Elevator')
        _header_style(ws.cell(row=row, column=2), 'Description')
        row += 1
        for lift in result.lifts:
            ws.cell(row=row, column=1).value = lift
            ws.cell(row=row, column=2).value = ''
            for col in range(1, 3):
                ws.cell(row=row, column=col).font = Font(name='Calibri', size=10)
                _border(ws.cell(row=row, column=col))
            row += 1

    _auto_width(ws)


def _sheet_notes(wb, result: ExtractionResult):
    ws = wb.create_sheet('Drawing Notes')

    ws['A1'].value = 'DRAWING NOTES & ANNOTATIONS'
    ws['A1'].font = Font(bold=True, size=12, name='Calibri')
    ws['A1'].alignment = Alignment(horizontal='center')
    ws.merge_cells('A1:B1')
    ws.row_dimensions[1].height = 20

    ws['A2'].value = 'Extracted from drawing annotation text. Verify against original drawing.'
    ws['A2'].font = Font(italic=True, size=9, name='Calibri')
    ws.merge_cells('A2:B2')

    row = 4
    _header_style(ws.cell(row=row, column=1), '#')
    _header_style(ws.cell(row=row, column=2), 'Note Text')
    row += 1

    if result.notes:
        for i, note in enumerate(result.notes, 1):
            ws.cell(row=row, column=1).value = i
            ws.cell(row=row, column=1).alignment = Alignment(horizontal='center', vertical='top')
            ws.cell(row=row, column=2).value = note
            ws.cell(row=row, column=2).alignment = Alignment(wrap_text=True, vertical='top')
            ws.cell(row=row, column=2).font = Font(name='Calibri', size=10)
            for col in range(1, 3):
                _border(ws.cell(row=row, column=col))
            ws.row_dimensions[row].height = max(18, min(len(note) // 5, 80))
            row += 1
    else:
        ws.cell(row=row, column=2).value = 'No annotation notes found.'

    ws.column_dimensions['A'].width = 5
    ws.column_dimensions['B'].width = 90


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

def generate_text_report(
    result: ExtractionResult,
    output_path: str,
    taxonomy_path: str = None,
) -> str:
    """
    Generate a plain-text report combining the best structure from all 5 AI result examples:
    - Document info header
    - Per-category sections with IDs listed
    - Category subtotals
    - Ductwork reference
    - Spaces served
    - Drawing notes
    - Grand summary table
    Returns the output_path written.
    """
    if taxonomy_path is None:
        taxonomy_path = os.path.join(os.path.dirname(__file__), 'taxonomy.json')
    taxonomy = _load_taxonomy(taxonomy_path)
    grouped = components_by_category(result, taxonomy)
    total = total_count(result)

    W = 80  # report width
    lines: List[str] = []

    def rule(char='='):
        lines.append(char * W)

    def heading(text):
        rule()
        lines.append(text.center(W))
        rule()

    def blank():
        lines.append('')

    heading('MECHANICAL SERVICES — COMPONENT EXTRACTION REPORT')
    blank()

    # Document information
    lines.append('DOCUMENT INFORMATION')
    rule('-')
    for label, value in [
        ('Drawing Number', result.drawing_number or 'N/A'),
        ('Floor / Level',  result.floor_level   or 'N/A'),
        ('Discipline',     result.discipline),
        ('Source File',    result.source_file),
        ('Processed Date', datetime.now().strftime('%Y-%m-%d %H:%M')),
    ]:
        lines.append(f'  {label:<20}: {value}')
    blank()

    # Equipment sections by category
    category_order = [
        'HVAC Equipment', 'Ventilation', 'Fire Safety',
        'Controls & Sensors', 'Controls', 'Pipework', 'Heating', 'Other',
    ]

    for cat in category_order:
        if cat not in grouped:
            continue

        subtotal = sum(item['count'] for item in grouped[cat])
        lines.append(f'SECTION: {cat.upper()}  (Subtotal: {subtotal} units)')
        rule('-')

        for item in grouped[cat]:
            code_line = f"  {item['full_name']} ({item['code']})"
            qty_label = f"Count: {item['count']}"
            pad = W - len(code_line) - len(qty_label)
            lines.append(code_line + ' ' * max(1, pad) + qty_label)

            # List IDs, wrapped at ~70 chars
            ids = item['ids']
            chunk_lines = _wrap_ids(ids, width=W - 6)
            for chunk in chunk_lines:
                lines.append(f'    {chunk}')
            blank()

        lines.append(f'  {"":>60}{"Subtotal: " + str(subtotal):>15}')
        blank()

    # Ductwork reference
    rule('=')
    lines.append('DUCTWORK REFERENCE  (not counted as equipment)'.center(W))
    rule('=')
    if result.round_ducts:
        lines.append(f'  Circular  : {", ".join(result.round_ducts)}')
    if result.rect_ducts:
        lines.append(f'  Rectangular : {", ".join(result.rect_ducts)}')
    if not result.round_ducts and not result.rect_ducts:
        lines.append('  No duct sizes found.')
    blank()

    # Spaces served
    rule('=')
    lines.append('SPACES SERVED  (context — not counted in equipment total)'.center(W))
    rule('=')
    if result.rooms:
        lines.append(f'  Rooms : {", ".join(result.rooms)}')
    if result.lifts:
        lines.append(f'  Lifts : {", ".join(result.lifts)}')
    if not result.rooms and not result.lifts:
        lines.append('  None identified.')
    blank()

    # Drawing notes
    rule('=')
    lines.append('DRAWING NOTES & ANNOTATIONS'.center(W))
    rule('=')
    if result.notes:
        for i, note in enumerate(result.notes, 1):
            wrapped = _wrap_text(note, W - 6)
            lines.append(f'  {i}. {wrapped[0]}')
            for cont in wrapped[1:]:
                lines.append(f'     {cont}')
            blank()
    else:
        lines.append('  No annotation notes found.')
    blank()

    # Summary table
    heading('COMPONENT SUMMARY TABLE')
    col_widths = [4, 22, 8, 30, 7]
    row_fmt = ' {:>{}}'.format
    header_parts = ['#', 'Category', 'Code', 'Full Name', 'Count']
    sep = '-' * W

    def table_row(num, cat, code, name, count):
        return (f'  {str(num):<4}{cat:<22}{code:<8}{name:<30}{str(count):>7}')

    lines.append(table_row('#', 'Category', 'Code', 'Full Name', 'Count'))
    lines.append(sep)

    row_num = 1
    for cat in category_order:
        if cat not in grouped:
            continue
        for item in grouped[cat]:
            lines.append(table_row(
                row_num, cat[:21], item['code'][:7], item['full_name'][:29], item['count']
            ))
            row_num += 1

    lines.append(sep)
    lines.append(table_row('', '', '', 'TOTAL EQUIPMENT', total))
    rule('=')
    blank()

    if result.warnings:
        lines.append('WARNINGS')
        rule('-')
        for w in result.warnings:
            lines.append(f'  ! {w}')
        blank()

    text = '\n'.join(lines)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(text)
    return output_path


def _sheet_combined(wb, result: ExtractionResult, combined_result, taxonomy: dict):
    """Sheet 3: Multi-source analysis with confidence colour coding."""
    ws = wb.create_sheet('Multi-Source Analysis')

    ws.merge_cells('A1:I1')
    ws['A1'].value = 'MULTI-SOURCE ANALYSIS — STAGE 1 (Text) + STAGE 2 (Vector) + STAGE 3 (ML)'
    ws['A1'].font  = Font(bold=True, size=12, name='Calibri')
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 20

    ws['A2'].value = (
        'Confirmed = text + vector agree  |  Text only = Stage 1 only  |  '
        'Unlabelled = vector/ML found symbol with no text label  |  '
        '⚑ = count discrepancy between sources'
    )
    ws['A2'].font = Font(italic=True, size=9, name='Calibri')
    ws.merge_cells('A2:I2')

    next_row = _doc_info_rows(ws, result, row=3)

    headers = ['Code', 'Full Name', 'Count', 'Stage 1 ✓', 'Stage 2 ✓', 'Stage 3 ✓',
               'Confidence', 'Component IDs', 'Notes']
    for col, h in enumerate(headers, 1):
        _header_style(ws.cell(row=next_row, column=col), h)
    next_row += 1

    # Confidence → openpyxl fill
    from result_combiner import CONFIRMED, TEXT_ONLY, UNLABELLED, ML_ONLY, CONFIDENCE_HEX
    conf_fills = {
        conf: PatternFill('solid', fgColor=hex_)
        for conf, hex_ in CONFIDENCE_HEX.items()
    }
    disc_font = Font(bold=True, color='CC0000', name='Calibri', size=10)
    norm_font = Font(name='Calibri', size=10)

    for comp in combined_result.components:
        s1 = '✓' if 'text'   in comp.sources else '—'
        s2 = '✓' if 'vector' in comp.sources else '—'
        s3 = '✓' if 'ml'     in comp.sources else '—'
        ids_str = ', '.join(comp.component_ids)
        info    = taxonomy.get(comp.component_type, {})
        prefix  = '⚑ ' if comp.discrepancy else ''
        fill    = conf_fills.get(comp.confidence, PatternFill())
        fnt     = disc_font if comp.discrepancy else norm_font

        row_vals = [
            comp.component_type,
            info.get('full_name', f'Unknown ({comp.component_type})'),
            comp.count,
            s1, s2, s3,
            prefix + comp.confidence,
            ids_str,
            info.get('notes', ''),
        ]
        for col, val in enumerate(row_vals, 1):
            c = ws.cell(row=next_row, column=col)
            c.value = val
            c.fill  = fill
            c.font  = fnt
            c.alignment = Alignment(
                vertical='top', wrap_text=True,
                horizontal='center' if col in (3, 4, 5, 6) else 'left'
            )
            _border(c)

        next_row += 1

    # Total row
    total = combined_result.total_count
    ws.cell(row=next_row, column=2).value = 'TOTAL EQUIPMENT'
    ws.cell(row=next_row, column=2).font  = Font(bold=True, name='Calibri', size=10)
    ws.cell(row=next_row, column=2).alignment = Alignment(horizontal='right')
    ws.cell(row=next_row, column=3).value = total
    ws.cell(row=next_row, column=3).font  = Font(bold=True, name='Calibri', size=11)
    ws.cell(row=next_row, column=3).alignment = Alignment(horizontal='center')
    for col in range(1, 10):
        c = ws.cell(row=next_row, column=col)
        c.fill = PatternFill('solid', fgColor=TOTAL_FILL)
        _border(c)

    # Unlabelled cluster note
    if combined_result.unlabelled_cluster_count:
        next_row += 2
        ws.cell(row=next_row, column=1).value = (
            f'⚑ {combined_result.unlabelled_cluster_count} unlabelled vector cluster(s) '
            'detected by Stage 2 — may be components missing a text label.'
        )
        ws.cell(row=next_row, column=1).font = Font(
            italic=True, color='CC6600', name='Calibri', size=10)
        ws.merge_cells(f'A{next_row}:I{next_row}')

    _auto_width(ws)
    ws.column_dimensions['H'].width = 55
    ws.column_dimensions['B'].width = 30


def _wrap_ids(ids: List[str], width: int = 70) -> List[str]:
    """Wrap a list of IDs into lines no longer than `width`."""
    lines, current = [], ''
    for i, id_ in enumerate(ids):
        sep = ', ' if i > 0 else ''
        if len(current) + len(sep) + len(id_) > width:
            lines.append(current)
            current = id_
        else:
            current += sep + id_
    if current:
        lines.append(current)
    return lines or ['(none)']


def _wrap_text(text: str, width: int) -> List[str]:
    """Simple word-wrap."""
    words = text.split()
    lines, current = [], ''
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = (current + ' ' + word).strip()
    if current:
        lines.append(current)
    return lines or ['']
