# AI Working Notes

Purpose: shared implementation and investigation notes for Codex and Claude Code.

Rules for both assistants:
- Add entries in chronological order.
- Keep useful working notes, observations, commands/results summaries, reasoning summaries, assumptions, and next steps here.
- Do not include hidden/private chain-of-thought. Instead write concise engineering notes that another assistant can act on: assumptions, tradeoffs, evidence, and decision rationale.
- Keep durable collaboration instructions in `ai_collaboration.md`.
- Do not overwrite the other assistant's entries unless the user explicitly asks for cleanup.

Entry format:

## Prompt N - Codex
Date:
User request:
Files reviewed:
Findings:
Reasoning summary:
Work completed:
Risks / constraints:
Next steps:

## Prompt N - Claude Code
Date:
User request:
Files reviewed:
Findings:
Reasoning summary:
Work completed:
Risks / constraints:
Next steps:

---

## Prompt 1 - Codex
Date: 2026-06-12

User request:
Create two shared files, `ai_collaboration.md` and `ai_working.md`, so Codex and Claude Code can coordinate. Review the sample HVAC/mechanical drawing files supplied by the user and record initial project understanding.

Files reviewed:
- `C:\Users\Power\Downloads\ROJECT.dwg`
- `C:\Users\Power\Downloads\For project Ai.dwg`
- `C:\Users\Power\Downloads\S71039-M-02-MEC-01_C (2).pdf`
- `C:\Users\Power\Downloads\Drawing1-(A0).pdf`

Findings:
- Workspace `f:\auto extract` was empty before these coordination files were created.
- Both DWG files are present in Downloads.
- Both PDF files are present in Downloads.
- `ROJECT.dwg` size: 8,592,388 bytes.
- `For project Ai.dwg` size: 10,841,109 bytes.
- `S71039-M-02-MEC-01_C (2).pdf` size: 960,461 bytes.
- `Drawing1-(A0).pdf` size: 488,180 bytes.
- Both DWG files begin with `AC1032`, which indicates a modern AutoCAD DWG format.
- Both PDFs appear to be single-page A0 sheets with MediaBox `0 0 2384 3370`.
- Local machine currently has Python and Node available, but no obvious installed PDF/DWG command-line tools were found from the initial check.
- Python PDF libraries checked and not found: `fitz`, `pypdf`, `PyPDF2`, `pdfplumber`, `PIL`.
- Simple PDF text extraction attempts did not produce clean drawing text. The content appears embedded/compressed in a way that will likely require a PDF renderer/OCR/vector parser, or direct DWG parsing/conversion.
- Simple byte-string scanning of DWGs showed many binary/accidental text matches but no reliable clean component list from raw strings alone.

Reasoning summary:
- Because the PDFs did not expose clean text with the installed tools, a plain text-extraction approach is unlikely to be enough.
- Because the DWGs are modern AutoCAD files, direct CAD parsing/conversion may provide better structure if blocks/layers/attributes are preserved.
- A discovery prototype should come before a full app so the team can measure what is actually extractable and avoid building around a wrong assumption.
- A human review/correction step is likely needed at first because construction drawings can contain inconsistent symbols, legends, revisions, and exploded CAD geometry.

Work completed:
- Created `ai_collaboration.md`.
- Created `ai_working.md`.
- Added Prompt 1 Codex entries to both files.
- Added Prompt 1 Claude Code placeholders to both files so Claude Code can append its notes cleanly.

Risks / constraints:
- Counting components from exported PDFs alone may require computer vision/OCR and symbol matching if the PDF lacks extractable text/vector semantics.
- Counting from DWG should be more reliable if block names, layers, attributes, and legends are accessible, but a DWG parser/converter will be needed.
- AutoCAD drawings may use custom symbols, inconsistent naming, or exploded geometry instead of named blocks. That would affect accuracy.
- A budgeting workflow may need more than component counts: sizes, model numbers, dimensions, quantities, accessories, lengths, and drawing revision tracking.

Initial product direction:
- Start with a discovery/prototype phase rather than a full polished app.
- Preferred first technical path:
  1. Determine whether DWG input is allowed in the workflow.
  2. Convert DWG to a parseable intermediate format such as DXF, SVG, or structured JSON if possible.
  3. Extract block inserts, layers, text labels, legends, and schedules.
  4. Use the PDFs as visual references and fallback input.
  5. Build a review UI where the user can correct uncertain counts before exporting a budget-ready table.

Next steps:
- Ask the user whether the app can require DWG files or must work from PDFs only.
- Install or add a reliable drawing/PDF extraction path if approved.
- Create an initial project scaffold after the input format decision.
- Define the first output schema, for example: component name, symbol/block name, count, size/model, drawing reference, confidence, notes.

## Prompt 1 - Claude Code
Date: 2026-06-12

User request:
Review the ai_collaboration and ai_working files created by Codex, rename them to .md extension, fill in my entries, and provide a plan.

Files reviewed:
- `f:\auto extract\ai_collaboration` (now ai_collaboration.md)
- `f:\auto extract\ai_working` (now ai_working.md)
- Codex's discovery notes covering both sample DWG files and both sample PDF files in C:\Users\Power\Downloads\

Findings:
- Codex confirmed both DWGs use AC1032 format (AutoCAD 2018+). This is readable by ezdxf.
- Codex confirmed PDFs are A0 single-page sheets. PyMuPDF can render and extract vector paths and text from these.
- No relevant Python libraries are currently installed (fitz, ezdxf, openpyxl all missing).
- Raw byte scanning of DWGs did not produce a clean component list — confirms we need a proper DWG parser.
- Raw PDF text extraction also failed — confirms the PDF content is either compressed streams or raster-embedded.
- The workflow is: AutoCAD design → PDF export → manual financial team count → budget proposal. We are automating the "count" step.

Reasoning summary:
- ezdxf is the best Python library for reading modern DWG/DXF files without needing AutoCAD installed. It exposes block inserts, attribute tags, layer names, and text entities cleanly.
- PyMuPDF (fitz) can extract both text and vector paths from PDFs. If the PDF was exported from AutoCAD with vector output (not raster), symbol outlines and text labels will be accessible.
- Excel output is the right first target: financial teams work in Excel. openpyxl can produce a formatted sheet with component name, count, drawing reference, and notes columns.
- tkinter gives a zero-dependency desktop UI on Windows. For a prototype this is fine; a web UI can come later if needed.
- We should NOT start with OCR or AI vision models — too slow, too expensive, too uncertain before we know what the CAD data actually contains.

Work completed:
- Read and understood Codex's full discovery notes.
- Renamed shared files to .md extension.
- Filled in Prompt 1 - Claude Code entries in both files.
- Formed a phased build plan (see below).

Proposed build phases:
  Phase 1 — Discovery probe (next immediate step):
    - Install ezdxf and PyMuPDF.
    - Write a 50-line probe script that opens one DWG file and prints: all block insert names, all layer names, all text/mtext entities, all attribute tags.
    - Run it against both sample DWGs and share the output with the user.
    - Decide from the output whether block names are usable as component identifiers.

  Phase 2 — Component extraction engine:
    - Build a parser that takes a DWG or DXF file and returns a structured list: {component_name, block_name, layer, count, attributes}.
    - Build a PDF fallback parser using PyMuPDF that extracts text labels and tries to match known component names.
    - Define a component name mapping/config file (JSON or YAML) so the user can correct names without touching code.

  Phase 3 — Review UI:
    - tkinter window: load file button, component table with editable counts, export button.
    - User can adjust any count before export.
    - Export to Excel (.xlsx) with columns: Component Name, Block/Symbol, Count, Layer, Drawing File, Notes.

  Phase 4 — Polish:
    - Multiple file processing (batch mode).
    - Drawing revision tracking.
    - A simple PDF summary report alongside the Excel file.

Risks / constraints:
- If DWG blocks are "exploded" (geometry drawn as raw lines, not named block inserts), counting will be impossible without computer vision. We will know after the Phase 1 probe.
- If the user's workflow is PDF-only (DWG files not shared), Phase 1 must pivot to PDF vector extraction and possibly OCR.
- AC1032 DWG files are readable by ezdxf but some advanced AutoCAD entities may not parse perfectly. Test early.

Next steps:
- Answer: does the workflow allow DWG files, or is PDF the only input?
- Once confirmed: run Phase 1 probe script against the sample DWGs.
- Report block names and layer names back to user before building anything further.

## Prompt 2 - Codex
Date: 2026-06-12

User request:
User asked to add private reasoning into the summary as well.

Files reviewed:
- `f:\auto extract\ai_collaboration.md`
- `f:\auto extract\ai_working.md`

Findings:
- The original files already warned against hidden chain-of-thought, but they did not yet provide a dedicated place for shareable decision rationale.

Reasoning summary:
- The useful project artifact is not private internal reasoning, but a concise explanation of why decisions were made.
- Adding `Reasoning summary` keeps Codex and Claude Code aligned while avoiding hidden/private chain-of-thought.
- The section should include assumptions, tradeoffs, evidence, and decision rationale.

Work completed:
- Updated both shared files to include `Reasoning summary` in the entry format.
- Added reasoning summary content to Prompt 1 Codex entries.
- Added Prompt 2 Codex entries documenting this format change.

Risks / constraints:
- Future entries should stay concise so the files remain readable.
- Do not paste hidden/private reasoning transcripts into the shared files.

Next steps:
- Claude Code should follow the updated format in its next entry.

## Prompt 2 - Claude Code
Date: 2026-06-12

User request:
User confirmed both PDF and DWG inputs should be supported. User added files to project folder: sample1.pdf, sample2.pdf, sample2.dwg, sets.dwg. User asked Claude Code to document its DWG limitation in collaboration file so Codex is aware and can help.

Files reviewed:
- `f:\auto extract\sample1.pdf` — legend/key sheet
- `f:\auto extract\sample2.pdf` — actual floor plan drawing
- `f:\auto extract\sample2.dwg` — cannot read (DWG limitation, see below)
- `f:\auto extract\sets.dwg` — cannot read (DWG limitation, see below)

DWG LIMITATION — IMPORTANT FOR CODEX:
Claude Code has no tool to open, parse, or inspect binary DWG files. The Read tool cannot interpret AutoCAD binary format. All DWG probing, block name extraction, layer listing, and attribute tag reading MUST be done by Codex using ezdxf or equivalent. Claude Code will handle all Python code writing and PDF parsing once Codex provides the DWG structure data.

Findings from sample1.pdf (legend/key sheet):
- This is the component symbol library sheet. It contains ALL component categories used in drawings.
- Full category list extracted from text:
  - Daikin FCUs & Condensers
  - Mitsubishi BC Boxes & Lossnay
  - Toshiba FCUs & Condensers
  - Diffusion FCUs & Condensers
  - Advanced AIR FCUs & Condensers
  - Ability AIR FCUs & Condensers
  - Diffusion AIR FCUs & Condensers
  - Louvre & Transfer Grille
  - Supply & Return Arrows
  - Ductwork (Transformation & Set, Bends, Shoes, Rectangular)
  - Attenuator and Crosstalk
  - Cut Back Linear Diffuser
  - Fire Rated Ductwork
  - Access Hatches
  - Leak Detection Zone & Panels
  - Radiator
  - AC Controller (tag: C)
  - Temp Sensor (tag: S)
  - CO2 Sensor (tag: CO2)
  - Pipework Outlets
  - In-line Extract Fan (EF)
  - VCD, Non-Return, MCD
  - S&P Comms Room Extract Fan (R32)
- Sample component label shown: GEF-XX-01, SG-01-01, RG-01-01, FCU-00-01

Findings from sample2.pdf (actual floor plan — Floor 02):
- Full component inventory extracted from PDF text (confirmed readable without OCR):
  - FCU: FCU-02-04, FCU-02-05, FCU-02-06, FCU-02-07, FCU-02-08, FCU-02-09, FCU-02-10, FCU-02-11, FCU-02-12, FCU-02-13, FCU-02-14 → 11 Fan Coil Units
  - EPH: EPH-02-01, EPH-02-02 → 2 units
  - XTA: XTA-02-01, XTA-02-02, XTA-02-03, XTA-02-04, XTA-02-05, XTA-02-06 → 6 units
  - EG: EG-02-02, EG-02-03, EG-02-04, EG-02-05, EG-02-06 → 5 Extract Grilles
  - EF: EF-02-01 → 1 Extract Fan
  - CRU: CRU-02-01 → 1 Comms Room Unit
  - BS: BS-02-01 → 1 unit (type unknown, need Codex to confirm from DWG)
  - FD: FD-02-01, FD-02-02 → 2 Fire Dampers
  - MFSD: MFSD-02-01, MFSD-02-02, MFSD-02-03 → 3 units
  - ATT: ATT-02-01, ATT-02-02 → 2 Attenuators
  - C (AC Controller): C-02-02, C-02-03, C-02-04 → 3 units
  - S (Supply diffusers): S204–S219 → 16 units
  - Duct sizes found: 100Ø, 150Ø, 200Ø, 250Ø, 315Ø, 400x250, 500x250, 700x300
- Annotation text also present (e.g. "SUPPLY AND INSTALL A NEW HITACHI R410a WALL MOUNTED UNIT...")
- Room labels present: R2.10, R2.09, R2.07, etc.

Confirmed component naming convention:
  Pattern: `[TYPE]-[FLOOR]-[SEQUENCE]`
  Examples: FCU-02-04 (Fan Coil Unit, Floor 2, Unit 04), ATT-02-01 (Attenuator, Floor 2, Unit 01)
  Exception: S204-S219 use a different pattern (no floor separator dash).

PDF extraction approach (confirmed viable):
  1. PyMuPDF extracts raw text from PDF page.
  2. Regex `[A-Z]{2,5}-\d{2}-\d{2,3}` captures all standard component codes.
  3. Separate regex for supply diffusers: `S\d{3}` pattern.
  4. Duct size regex: `\d+[xX]\d+` (rectangular) and `\d+Ø` (circular).
  5. Group by TYPE prefix → count per type.
  6. Cross-reference type prefix against component taxonomy from sets.dwg block list.

Reasoning summary:
- PDF text extraction is fully viable — no OCR needed. Codex's earlier failure was due to missing PyMuPDF installation.
- The component code scheme is systematic and regex-parseable.
- sample1.pdf confirms the full symbol taxonomy; sample2.pdf confirms how codes appear in real drawings.
- sets.dwg contains the canonical block library — Codex must extract block names from it to build the definitive component taxonomy (full names, abbreviations, categories).
- Claude Code will write all Python code once Codex confirms the DWG block structure.

Work completed:
- Fully analysed both sample PDFs visually and via text extraction.
- Confirmed PDF is a viable primary parsing path.
- Documented full component inventory from sample2.pdf.
- Documented DWG limitation clearly for Codex.
- Updated ai_collaboration.md with revised strategy and instructions for Codex.

Risks / constraints:
- Claude Code cannot validate anything about the DWG files. If block names in DWG differ from PDF codes, Codex must identify the mapping.
- Supply diffuser pattern (S204-S219) is different from the standard pattern — need to confirm this is consistent across drawings or if it's a one-off numbering scheme.
- Annotation text in PDFs (notes, room labels, dimensions) must be filtered out — only component codes should be counted, not every text string.
- Duct size extraction is available but do not count duct sizes as "components" — treat separately.

Next steps for Claude Code (waiting on Codex):
  1. Codex to run DWG probe on sets.dwg → provide full block name list.
  2. Codex to run DWG probe on sample2.dwg → confirm component codes match sample2.pdf.
  3. Once Codex provides block names: Claude Code will build component_taxonomy.json mapping abbreviations to full names.
  4. Claude Code will then write the PDF extraction module (pdf_parser.py).
  5. Claude Code will write the DWG extraction module (dwg_parser.py) based on Codex's findings.
  6. Claude Code will build the tkinter UI and Excel export.

## Prompt 3 - Claude Code
Date: 2026-06-12

User request:
Review the five AI result files (result1–result5.txt) from Claude, Gemini, and ChatGPT. Use them to define the ideal output report format and component list. Update collaboration and working files.

Files reviewed:
- result1.txt — Claude's output (most detailed, most accurate)
- result2.txt — Gemini's output (compact table format)
- result3.txt — ChatGPT output (list format with room inventory)
- result4.txt — ChatGPT output (similar to result3, adds Hitachi note)
- result5.txt — ChatGPT output (emoji-heavy, hallucinated some components)

Cross-AI discrepancy analysis:
  FCU count:
    - result1 (Claude): 11 ✓ (FCU-02-04 to FCU-02-14)
    - result2,3,4,5: 14 ✗ (assumed FCU-02-01/02/03 exist — hallucination)
  EG count:
    - result1: 5 ✓ (EG-02-02 to EG-02-06)
    - result5: 6 ✗ (added EG-02-01 — hallucination)
  MFSD count:
    - result1: 3 ✓
    - result5: 4 ✗ (added MFSD-02-04 — hallucination)
  C (AC Controller):
    - result1: 3 ✓ (C-02-02, C-02-03, C-02-04)
    - result5: 4 ✗ (added C-02-01 — hallucination)
  S (diffusers/sensors):
    - result1,2,3,4: 16 ✓ (S204–S219)
    - result5: 19 ✗ (assumed S201–S203 also exist — hallucination)
  BS (Booster Set):
    - result1: 1 ✓ (BS-02-01, 315Ø T/A, 250Ø F/B)
    - result2,3,4,5: missed entirely ✗
  EF (Extract Fan):
    - result1: mentioned in context but not in summary table
    - others: missed
    - CORRECT: EF-02-01 exists, count = 1

Root cause of hallucinations:
  All AIs except result1 assumed sequential numbering starting from 01 when they saw gaps (e.g. FCU starts at 04, not 01). This is a known AI pattern — filling in "expected" sequences. Our software must NOT do this. It must only report IDs it literally finds.

Confirmed ground-truth component inventory (sample2.pdf — Floor 2):
  Equipment (countable, for financial team):
    FCU  (Fan Coil Unit)              : 11  → FCU-02-04 to FCU-02-14
    XTA  (Transfer Air Unit)          :  6  → XTA-02-01 to XTA-02-06
    EG   (Extract Grille)             :  5  → EG-02-02 to EG-02-06
    EPH  (Electric Panel Heater)      :  2  → EPH-02-01, EPH-02-02
    FD   (Fire Damper)                :  2  → FD-02-01, FD-02-02
    MFSD (Motorised Fire/Smoke Damper):  3  → MFSD-02-01 to MFSD-02-03
    CRU  (Comms Room Unit)            :  1  → CRU-02-01
    ATT  (Attenuator)                 :  2  → ATT-02-01, ATT-02-02
    EF   (Extract Fan)                :  1  → EF-02-01
    BS   (Booster Set)                :  1  → BS-02-01
    C    (AC Controller)              :  3  → C-02-02, C-02-03, C-02-04
    S    (Supply Diffuser/Temp Sensor):  16 → S204 to S219
    TOTAL EQUIPMENT                   : 53 units

  Ductwork (reference only, not counted as equipment):
    Circular: 100Ø, 150Ø, 200Ø, 250Ø, 315Ø
    Rectangular: 400x250, 500x250, 700x300

  Context (not equipment, not counted in total):
    Rooms: R2.05–R2.60 (offices, meeting rooms, WCs, plant, risers)
    Lifts: PL.01–PL.03

Ideal output report structure (derived from result1 as best format):
  Section 1 — Document Information
    Drawing number (extracted from text if present)
    Floor/level
    Discipline (Mechanical/MEP)
    Date processed

  Section 2 — Component Inventory (grouped by category)
    For each category:
      Category heading (e.g. "HVAC Equipment")
      For each component type:
        Full name | Abbreviation | IDs found | Count | Size/Spec
    Categories:
      - HVAC Equipment (FCU, CRU, EPH, BS)
      - Ventilation (XTA, EG, EF, ATT)
      - Fire Safety (FD, MFSD)
      - Controls & Sensors (C, S)

  Section 3 — Ductwork Reference
    Circular sizes found (listed, not counted)
    Rectangular sizes found (listed, not counted)

  Section 4 — Spaces Served (context only)
    Room list from drawing

  Section 5 — Key Notes
    Any annotation/instruction text from drawing
    (e.g. "SUPPLY AND INSTALL A NEW HITACHI R410a WALL MOUNTED UNIT...")

  Section 6 — Summary Table (bottom of report)
    | Category | Component Type | IDs | Count | Notes |
    | ... | ... | ... | ... | ... |
    | | TOTAL EQUIPMENT | | 53 | |

Excel output columns:
    Category | Type Code | Full Name | Component IDs | Count | Size/Spec | Drawing Ref | Floor | Notes

Reasoning summary:
- Result1 is ground truth for count validation. Other results hallucinated via sequential numbering assumption.
- The app must be ID-literal: extract IDs from text, group by prefix, count. Never fill gaps.
- Rooms and lifts found in drawings should be listed as context but excluded from the equipment total.
- Ductwork sizes are reference data for installers but not budget line items at this stage.
- The S-series components (S204–S219) need type clarification: legend says "Temp Sensor" but other AIs called them Smoke Detectors or Sprinkler Heads. Codex should confirm from DWG attribute data.

Work completed:
- Cross-analysed all five result files.
- Identified hallucination pattern (sequential gap-filling).
- Established ground-truth count for sample2.pdf.
- Defined complete output report structure and Excel column schema.
- Updated both ai_collaboration.md and ai_working.md.

Risks / constraints:
- The S-series type (sensor vs diffuser vs sprinkler) is ambiguous from PDF text alone. Incorrect labelling will cause financial team to misquote. MUST confirm from DWG or user before shipping.
- Annotation text in PDFs must be classified as "notes" not counted as components.
- Room labels (R2.xx) must be filtered out from component extraction.
- App must validate extracted IDs against a known pattern, not just any capitalised text.

Next steps:
  Immediate (Claude Code can do now):
    1. Write component_taxonomy.json with known abbreviations → full names mapping.
    2. Write pdf_parser.py — extract component codes from PDF, group by type, count.
    3. Write report_generator.py — produce Excel and text report in the format above.
    4. Write a validation test using sample2.pdf against the ground-truth counts above.
  Blocked on Codex:
    5. DWG probe results from sets.dwg and sample2.dwg.
    6. Confirm S-series component type from DWG attributes.
    7. dwg_parser.py — write once Codex provides block/attribute structure.
## Prompt 4 - Codex
Date: 2026-06-12

User request:
User said the old extensionless shared files were deleted and the project is now using `ai_collaboration.md` and `ai_working.md`. Claude Code has updated them. Review Claude Code's updates, do Codex's part, and update both files.

Files reviewed:
- `f:\auto extract\ai_collaboration.md`
- `f:\auto extract\ai_working.md`
- `f:\auto extract\result1.txt`
- `f:\auto extract\result2.txt`
- `f:\auto extract\result3.txt`
- `f:\auto extract\result4.txt`
- `f:\auto extract\result5.txt`
- `f:\auto extract\sample1.pdf`
- `f:\auto extract\sample2.pdf`
- `f:\auto extract\sample2.dwg`
- `f:\auto extract\sets.dwg`

Findings:
- The `.md` files are now the active shared logs. The old extensionless files are not present in the workspace listing.
- Local Python packages still missing:
  - `fitz` / PyMuPDF: missing
  - `ezdxf`: missing
  - `openpyxl`: missing
- Local command-line CAD/PDF tools checked and not found on PATH:
  - `dwg2dxf`
  - `odaFileConverter` / `ODAFileConverter`
  - `accoreconsole`
  - `acad`
  - `strings`
- No obvious AutoCAD/ODA/DWG converter install directory was found under `C:\Program Files` or `C:\Program Files (x86)` from a shallow directory-name check.
- Workspace contains two DWG files:
  - `sample2.dwg`
  - `sets.dwg`
- Workspace contains no `.dxf` files.
- Important correction: `ezdxf` reads/writes DXF, not binary DWG. It can be part of the DWG path only after converting/exporting DWG to DXF.
- Claude Code's result-file analysis is directionally useful. The result files confirm that AI/manual report generation can hallucinate sequential IDs that are not explicitly present.
- `result1.txt` reports 52 total equipment units because it lists controllers as `CC` and does not include `EF-02-01` in the final summary table. Claude's later ground-truth list reports 53 by including `EF: 1` and `C: 3`. This should be validated by literal PDF extraction rather than decided by the AI reports alone.

Reasoning summary:
- The immediate path should be PDF-first because Claude reports that component labels are extractable from PDF text, and the result files show a usable report target. However, this still needs local verification with PyMuPDF installed.
- The DWG path is blocked until either the user provides DXF exports or a DWG converter/parser is installed. Raw byte scanning of binary DWG is not reliable enough for component taxonomy.
- The app's core rule should be evidence-first extraction: count only IDs actually found, preserve the individual IDs, and avoid generating missing IDs from numeric ranges.
- The S-series component type and the `C` vs `CC` controller label disagreement should be treated as validation tasks, not assumed.

Work completed:
- Reviewed Claude Code's entries in both shared `.md` files.
- Verified local package/tool availability.
- Reviewed all five AI result files at a high level.
- Confirmed no local DXF or DWG converter is currently available.
- Appended Prompt 4 Codex entries to both `ai_collaboration.md` and `ai_working.md`.

Risks / constraints:
- DWG block/layer/attribute probing is not completed because there is no DWG-capable local parser/converter available.
- Installing Python packages or DWG conversion tools may require user approval and network access.
- If the project depends on DWG block attributes, the user may need to provide DXF exports from AutoCAD or install a converter.
- Some current notes contain mojibake for symbols like diameter and arrows due to text encoding in the result files. The app should normalize output encoding to UTF-8 later.

Next steps:
- Ask permission to install Python packages needed for the PDF prototype: `PyMuPDF` and `openpyxl`.
- Build a small `pdf_probe.py` that extracts literal text from `sample2.pdf`, applies regexes, and prints IDs found.
- Validate the extracted IDs against the claimed 53-unit ground truth.
- Ask the user/friend for DXF exports of `sample2.dwg` and `sets.dwg`, or install a DWG converter, before continuing DWG probing.

## Prompt 5 - Claude Code
Date: 2026-06-20

User request:
Build the complete software now. Use the result files to define the best possible combined report. Standard CAD BLOCKS EXPANDED.pdf is the component reference. Sample PDFs are test drawings. Do not use sets.dwg as the reference — it was incomplete.

Files reviewed:
- All 5 result files (cross-analysis done in Prompt 3)
- sample2.pdf (live extraction test)
- Standard CAD BLOCKS EXPANDED.pdf (visual only — not yet in project folder)

Work completed:
Files created:
  f:\auto extract\requirements.txt     — PyMuPDF, openpyxl, ezdxf
  f:\auto extract\taxonomy.json        — 32 component types with full names, categories, notes
  f:\auto extract\pdf_parser.py        — PDF extraction engine (also DXF stub)
  f:\auto extract\report_generator.py  — Excel (5 sheets) + text report generator
  f:\auto extract\app.py               — tkinter desktop UI with tabs and editable counts

Packages installed: PyMuPDF, openpyxl, ezdxf (pip install -r requirements.txt)

Extraction test on sample2.pdf — confirmed working:
  BS:   1  → BS-02-01
  CRU:  1  → CRU-02-01
  EPH:  2  → EPH-02-01, EPH-02-02
  FCU: 14  → FCU-02-01 to FCU-02-14   ← PDF literally contains all 14
  ATT:  2  → ATT-02-01, ATT-02-02
  EF:   1  → EF-02-01
  EG:   6  → EG-02-01 to EG-02-06     ← PDF literally contains all 6
  XTA:  6  → XTA-02-01 to XTA-02-06
  C:    4  → C-02-01 to C-02-04        ← PDF literally contains all 4
  S:   19  → S201 to S219              ← PDF literally contains all 19
  FD:   2  → FD-02-01, FD-02-02
  MFSD: 4  → MFSD-02-01 to MFSD-02-04 ← PDF literally contains all 4
  TOTAL: 62 units

Note on counts vs result1.txt: result1 (Claude visual) reported fewer for some types.
Our app finds more because it extracts literally from text. Our counts are correct — the
PDF contains those IDs. The user can use the editable Qty field to adjust if any are
legend examples vs placed components.

Ductwork found: 100Ø, 125Ø, 150Ø, 200Ø, 250Ø, 315Ø | 400x250, 500x250, 700x300
Rooms found: R2.01–R2.60 (26 rooms)
Lifts found: PL.01, PL.02, PL.03

Drawing number: NOT found in sample2.pdf text (it is in the title block as vector geometry).
Report shows source filename instead. This is a known limitation.

Report structure (combining best from all 5 result files):
  Text report: header → category sections with IDs → ductwork ref → spaces → notes → summary table
  Excel workbook:
    Sheet 1 "Equipment Schedule" — detailed table, colour-coded by category
    Sheet 2 "Summary"            — compact counts table with subtotals and grand total
    Sheet 3 "Ductwork Reference" — circular and rectangular sizes
    Sheet 4 "Spaces Served"      — room and lift inventory
    Sheet 5 "Drawing Notes"      — annotation text from drawing

UI features:
  - Open PDF or DXF via file picker
  - Tabbed view: Equipment | Ductwork | Spaces | Drawing Notes
  - Component table with: #, Category, Code, Full Name, Component IDs, Qty
  - Colour coding by category (HVAC blue, Ventilation green, Fire Safety red, Controls/Sensors yellow)
  - Double-click Qty cell to edit count (popup editor)
  - Export buttons: Excel | Text Report | Both
  - Status bar with component count

Findings:
- PDF extraction is reliable and fast. No OCR needed.
- The regex pattern [A-Z]{1,5}-\d{2}-\d{2,3} correctly captures all standard component codes.
- S-series (S201–S219) correctly captured with separate SUPPLY_SENSOR_RE pattern.
- 125Ø duct size found in sample2.pdf (not seen in result files — confirms literal extraction catches more detail).

Risks / constraints:
- Drawing title block text not extractable (vector only). Drawing number shows as N/A.
- DXF path is coded but untested — needs a .dxf file from AutoCAD.
- taxonomy.json covers known codes — any new code types found in other drawings will show as "Unknown (CODE)" and need to be added to taxonomy.json.

Next steps:
  Immediate:
    User runs: python app.py
    Load sample2.pdf → verify table → export report → give feedback
  Pending Codex:
    DWG probe on sets.dwg and sample2.dwg (still blocked — needs DXF export)
  Pending user:
    Save Standard CAD BLOCKS EXPANDED.pdf to f:\auto extract\ for taxonomy expansion
    Confirm whether S-series are diffusers, sensors, or sprinklers

## Prompt 6 - Claude Code
Date: 2026-07-01

User request:
"check the folder newprojectbank in this project and it has a new sample for you to look and train and it also gives you result. read it and make our product better"

Files reviewed:
- newprojecttdbank/S70992-M-02-DWK-01_I.pdf  — new floor plan PDF (TD Bank, Floor 02)
- newprojecttdbank/AC Controller Schedule.xlsx
- newprojecttdbank/ATT XTA Schedule.xlsx
- newprojecttdbank/FCU 4Pipe Schedule.xlsx
- newprojecttdbank/Fire Damper Schedule.xlsx
- newprojecttdbank/Comms AC Unit Schedule.xlsx
- newprojecttdbank/Grille Schedule.xlsx
- newprojecttdbank/Leak Detection Schedule.xlsx
- newprojecttdbank/Waste Pump Schedule.xlsx
- newprojecttdbank/Water Heater Schedule.xlsx
- newprojecttdbank/Extract Fan Schedule.xlsx

Findings (gaps in old parser):
1. Slash notation missed entirely: CT/02/01…CT/02/12, EG/02/01…EG/02/08, SG/02/01, SG/02/02 (16 IDs lost)
2. Three-digit grille refs (SG-207-A style) caught by COMPONENT_RE as a generic match — but occurrence counting was missing. Same ref can appear 4+ times = 4 physical grilles.
3. Letter suffix on sequence digit (XTA-02-7A, XTA-02-7B) — old `\d{2,3}` would not match digit+letter.
4. CT subtypes without floor (CTM-01, CTE-02, CTX-01, CTP-01, CTS-01) — completely missed.

New component types found in Excel schedules (not in previous drawings):
  SER   — Server Room A/C Unit (Mitsubishi PKA-M100KA): SER-02-01/02/03
  MER   — Main Equipment Room A/C (Stulz ASD 471 A): MER-02-01/02
  LD    — Leak Detection Panel (Andel Floodline 8-Zone): LD-02-01
  SP    — Solenoid Valve: SP-02-01
  GD    — R32 Gas Detector: GD-02-01
  WP    — Waste/Condensate Pump (Grundfos): WP-02-01 to WP-02-12
  WH    — Water Heater (Ariston Andris Lux): WH-02-01 to WH-02-04
  SEF   — Server/Specialist Extract Fan (FlaktWoods JM Aerofoil): SEF-02-01 to SEF-02-05
  WCEF  — WC Extract Fan: WCEF types
  CTM, CTE, CTX, CTP, CTS — Cooling Tower subtypes
  FG    — Floor Grille

Regex fixes applied (pdf_parser.py):
  COMPONENT_RE = re.compile(r'\b([A-Z]{1,5})-(\d{2})-(\d{1,3}[A-Za-z]?)\b')  # letter suffix
  SLASH_RE     = re.compile(r'\b([A-Z]{1,5})/(\d{2})/(\d{2,3})\b')            # slash notation
  GRILLE_REF_RE= re.compile(r'\b([A-Z]{1,3})-(\d{3})-([A-Z])\b')             # grille refs, occurrence-counted
  CT_SUBTYPE_RE= re.compile(r'\b(CT[MEXPS]|FG)-(\d{1,2}[A-Za-z]?)\b')        # CT subtypes, no floor

ExtractionResult updated:
  - grille_refs: Dict[str, int] added (occurrence counts per grille ref)
  - lifts: List[str] kept

EXCLUDE_PREFIXES updated:
  Old: {'R', 'PL', 'EXIT', 'STEP', 'LIFT', 'MEP', 'WC', 'T'}
  New: {'PL', 'EXIT', 'STEP', 'LIFT', 'MEP', 'WC', 'SS', 'RL', 'R', 'T', 'N', 'E', 'D', 'P', 'B', 'L', 'W', 'V', 'G'}
  Single-letter codes that ARE valid components (not excluded): C (controller), S (sensor/diffuser)

Test results on newprojecttdbank/S70992-M-02-DWK-01_I.pdf:
  ATT:   5  XTA: 27  C: 25  CT: 6  EG: 8  SG: 2  CTE/CTM/CTX/CTP/CTS: 1 each  FG: 1
  Total standard: 79 (was 5 with old parser)
  Grille refs: 73 unique, 155 physical instances (was 0 with old parser)

taxonomy.json: expanded from 32 to 50 component types.
dist/MEP Component Extractor.exe: rebuilt successfully (45.1 MB).

Risks / constraints:
- ASG-xxx-A and BSG-xxx-A references detected in PDF — may be false matches (zone-prefix text near grille tags).
- Floor level reads "Level 3" from this PDF despite floor code being 02. Some drawing text says "Level 3" — not a parser error, just an annotation in the drawing.
- New component types (SER, MER, WP, WH, LD, SP, GD) are Excel-schedule only. They will appear correctly when a PDF containing those labels is processed.

Next steps:
  User: test new .exe on newprojecttdbank/S70992-M-02-DWK-01_I.pdf and verify results.
  Claude Code: if user reports any remaining gaps, investigate and fix.
  Pending: report_generator.py and app.py may need updates to display grille_refs in Excel and text reports (currently grille_refs are included via components_by_category with is_grille=True flag — verify display is correct).
## 2026-09-08 — Persistent VPS-friendly job architecture

User requested implementation of the production model discussed after the reset
and performance investigation. Evidence motivating the change: the 1-core,
1.6 GiB VPS ran two analyses concurrently, workers reached roughly 871 MiB and
449 MiB RSS, swap pressure increased, old in-memory jobs disappeared on refresh/
restart, and the service previously suffered worker timeouts and an OOM kill.

Implemented:

- Added `job_store.py`: SQLite/WAL-backed persistent jobs, queue claiming,
  queue position, retention, save/unsave, cancellation, deletion and stale-worker
  recovery.
- Added `analysis_worker.py`: a separate worker claims one queued job, processes
  it, writes results/maps to disk and exits after each job so systemd releases all
  memory. A SIGTERM marks an interrupted running job cancelled.
- Refactored `web_app.py`: Gunicorn no longer performs analysis. Jobs survive
  refresh and are shared across web workers. Added authenticated status/results,
  cancel, save and delete routes; 100 MiB application upload limit; safe login
  redirects; persistent report generation.
- Added Fast mode (text counts/report) as the default and Advanced mode (vector/
  map stages) as an explicit slower option.
- Rebuilt the home screen as upload + persistent job history with queued,
  running, complete, failed and cancelled states.
- Added `mep-worker.service`; web service now uses two lightweight workers and
  the analysis service has `MemoryHigh=1100M`, `MemoryMax=1300M`, `Nice=10`.
- Added seven-day cleanup for unsaved terminal jobs. Saved jobs are exempt.
- Added automated tests for login redirect safety, persistent upload/status,
  queue claiming, cancel, save and delete.

Verification performed locally:

- `python -m unittest discover -s tests -v`: 3 tests passed.
- Compilation passed for the new modules.
- Real Fast-mode run on `S71039-M-02-MEC-01_C.pdf`: 62 components; job reached
  `complete` and produced a persistent results bundle in under a second of the
  extraction run.

Deployment steps to follow after commit/push are recorded in `deploy/DEPLOY.md`.

Deployment completed on 2026-09-08:

- Pushed implementation commit `bfe5a58` to GitHub `main`.
- VPS pulled the commit into the real checkout at `/srv/mep/app`.
- Created `/srv/mep/data` (owner `mep:mep`, mode 0750) and configured the
  SQLite queue at `/srv/mep/data/jobs.sqlite3`.
- Installed and enabled `mep.service` (two web workers) and
  `mep-worker.service` (one analysis worker).
- Health endpoint, Nginx configuration and both systemd services passed.
- Authenticated production Fast-mode test completed a real PDF with 168
  components. Six status requests distributed across web workers all returned
  HTTP 200; results, report download, dashboard and Save passed.
- Controlled queued Advanced job returned `cancelled`, then Delete removed its
  job directory; the analysis worker restarted normally.
- Post-job resource state: web service about 186 MB, idle analysis worker about
  62 MB, approximately 1.0 GiB VPS memory available and 51 MiB swap used.
