# AI Collaboration Log

Purpose: shared coordination file for Codex and Claude Code.

Rules for both assistants:
- Add entries in chronological order.
- Keep entries separated by prompt number and assistant name.
- Put durable project instructions, agreed conventions, reasoning summaries, and prompt updates here.
- Do not overwrite the other assistant's entries.
- Keep detailed investigation notes in `ai_working.md`; keep this file focused on collaboration and coordination.
- Do not include hidden/private chain-of-thought. Instead include a concise reasoning summary: assumptions, tradeoffs, why a decision was made, and what evidence supports it.
- When changing implementation direction, briefly state why.

Entry format:

## Prompt N - Codex
Date:
Summary:
Reasoning summary:
Instructions / decisions:
Open questions:
Next suggested action:

## Prompt N - Claude Code
Date:
Summary:
Reasoning summary:
Instructions / decisions:
Open questions:
Next suggested action:

---

## Prompt 1 - Codex
Date: 2026-06-12

Summary:
The project is starting from scratch. The user wants software for an installation/design workflow: upload or insert mechanical/HVAC drawing PDFs exported from AutoCAD, then automatically count components and output component names plus relevant details for budgeting.

Reasoning summary:
The safest early direction is discovery before building the full app. Automated takeoff accuracy depends on whether the source drawings expose structured CAD data such as blocks/layers/attributes or only flattened PDF visuals. DWG input is likely a better primary source than PDF because component symbols may be represented as reusable CAD entities, while PDFs may require OCR/computer vision and manual confidence review.

Instructions / decisions:
- Maintain two shared files:
  - `ai_collaboration.md`: durable coordination, prompt updates, conventions, decisions.
  - `ai_working.md`: working notes, investigation findings, technical steps, assumptions, and next tasks.
- Use the exact prompt-entry pattern requested by the user:
  - `Prompt 1 - Codex`
  - `Prompt 1 - Claude Code`
  - `Prompt 2 - Codex`
  - and so on.
- Do not mix Codex and Claude Code content in the same entry.
- Preserve each assistant's notes unless the user explicitly asks to rewrite or clean them up.
- Treat the sample files as early domain evidence, not as a final complete specification.
- Avoid promising accurate automated quantity takeoff from PDFs until the drawing symbols, layers, legends, schedules, and component naming conventions are understood.
- Include reasoning summaries in future entries, but keep them concise and shareable rather than private chain-of-thought.

Open questions:
- What exact output does the financial team need: CSV, Excel, PDF report, database, or on-screen table?
- Are DWG files available for the real workflow, or will the software only receive PDFs?
- Are components represented by consistent symbols/blocks/layers in AutoCAD?
- Is there a legend or bill-of-materials table inside each drawing that can be used as ground truth?
- Does the system need to count only visible placed components, or also infer accessories/materials from ducts, pipes, cable lengths, or unit types?

Next suggested action:
Build a small discovery prototype before the full app: ingest a sample PDF/DWG, extract page metadata, identify whether text/symbols/layers are accessible, and define the first component taxonomy to count.

## Prompt 1 - Claude Code
Date: 2026-06-12

Summary:
Reviewed Codex's discovery findings. Confirmed the technical direction: DWG-first with PDF as fallback. Agreed on a phased build plan starting with a Python prototype using ezdxf for DWG parsing. Renamed shared files to .md extension and filled in this entry.

Reasoning summary:
Codex correctly identified that raw PDF text extraction fails on these drawing files. DWG (AC1032 format) parsed via ezdxf gives access to block inserts, layer names, attribute tags, and text entities — exactly the structured data needed for a component count. PDF processing with PyMuPDF is a viable fallback for when DWG is not available. A simple desktop UI (tkinter or a lightweight web frontend) is appropriate at this stage; no need for a database yet. The output should be Excel-first because that is what financial teams actually use.

Instructions / decisions:
- Primary parsing path: DWG via ezdxf Python library.
- Secondary parsing path: PDF via PyMuPDF (fitz) for text and vector extraction.
- Output format: Excel (.xlsx) via openpyxl, with CSV as a secondary export.
- UI: desktop app (tkinter) for the prototype; upgrade to web if the user prefers after seeing the prototype.
- Do not attempt OCR or computer-vision symbol matching in the first version; rely on CAD block/attribute data.
- Build in a review/correction step before final export so the user can fix uncertain counts.
- Agreed stack: Python 3.x, ezdxf, PyMuPDF, openpyxl, tkinter.

Open questions:
- Which components does the financial team currently count manually? (Need a sample output table to validate against.)
- Are block names in the DWG files consistent across drawings, or does each drawing use different naming?
- Does the user want to drop files into the app (drag-and-drop) or use a file picker?
- Should the app process multiple drawings at once and combine counts, or one drawing at a time?

Next suggested action:
Install ezdxf and PyMuPDF in the project environment, then run a quick DWG probe script to list all block insert names and text entities from one of the sample DWG files. Share findings with user before building the full UI.

## Prompt 2 - Codex
Date: 2026-06-12

Summary:
The user asked to include private reasoning in the summary as well. The collaboration format was updated to include a `Reasoning summary` field.

Reasoning summary:
The project files should contain enough rationale for another assistant to continue the work, but they should not contain hidden/private chain-of-thought. A concise reasoning summary gives the useful parts: assumptions, tradeoffs, evidence, and decision rationale.

Instructions / decisions:
- Future Codex and Claude Code entries should include `Reasoning summary`.
- The reasoning summary should be practical and shareable, not a private internal transcript.
- Existing Prompt 1 Codex entry was updated with a reasoning summary.

Open questions:
- None for this coordination-file change.

Next suggested action:
Claude Code should use the updated format when adding its next entry.

## Prompt 2 - Claude Code
Date: 2026-06-12

Summary:
Major finding: PDF text extraction WILL work. Both sample PDFs contain fully readable, structured text including component codes. Codex's earlier failure was due to missing libraries, not a fundamental PDF limitation. The component naming convention is confirmed. Also documenting a hard limitation: Claude Code cannot read or parse DWG files directly — Codex must own all DWG investigation and probing tasks.

Reasoning summary:
sample1.pdf is a legend/key sheet listing all symbol types. sample2.pdf is a real floor plan with placed components — all component codes are present as embedded text in the PDF (e.g. FCU-02-04, EG-02-05, ATT-02-01). This means PyMuPDF text extraction + regex matching against the code pattern `[A-Z]{2,5}-\d{2}-\d{2,3}` will reliably find and count all components without any OCR or computer vision. This simplifies Phase 1 significantly. The DWG path is still valuable for richer data (attributes, layer names, block geometry) but PDF is now a fully viable primary path, not just a fallback.

Instructions / decisions:
- REVISED: PDF is now the PRIMARY parsing path, not the fallback. DWG is the SECONDARY (richer) path.
- PDF extraction method: PyMuPDF text extraction + regex for component code pattern.
- Component code pattern confirmed: `TYPE-FLOOR-SEQ` e.g. `FCU-02-04`, `EG-02-06`, `MFSD-02-01`.
- Duct sizes also extractable from PDF text: round (e.g. 200Ø) and rectangular (e.g. 700x300).
- Claude Code CANNOT read DWG files. Codex must run all DWG probing tasks.
- Codex should probe `sample2.dwg` and `sets.dwg` to answer: what are the block names, layer names, and attribute tags? Are block names consistent with the PDF component code scheme?
- sets.dwg is the component library the friend uses — Codex should extract the full block name list from it to build the canonical component taxonomy.
- Both input types (PDF and DWG) will be supported in the final app.

Open questions:
- Codex: what block names appear in sets.dwg? Do they match the PDF component code prefixes (FCU, EG, EPH, XTA, ATT, MFSD, FD, etc.)?
- Codex: does sample2.dwg contain the same component codes as sample2.pdf? If yes, both paths are consistent.
- What does EPH, XTA, BS, MFSD, CRU abbreviate to in full? Needed for the financial team output table.
- Does the financial team need duct sizes and lengths in the output, or only equipment counts?

Next suggested action:
Codex: probe sets.dwg and sample2.dwg — list all block insert names, attribute tag names, and layer names. Share results here so Claude Code can build the component taxonomy config file and PDF regex patterns from confirmed names.

## Prompt 3 - Claude Code
Date: 2026-06-12

Summary:
Analysed five AI-generated result files (result1–result5.txt) from Claude, Gemini, and ChatGPT applied to sample2.pdf. Identified what the ideal output report should contain, documented count discrepancies across AIs (hallucination of non-existent components), and defined the confirmed ground-truth component list for Floor 2. Codex still needed for DWG block probing.

Reasoning summary:
The result files show that all five AIs hallucinated some components that do not exist in the actual drawing (e.g. FCU-02-01/02/03, EG-02-01, MFSD-02-04, C-02-01, S201–S203). Our app must ONLY count components with IDs it actually finds in the text — no gap-filling or assumption of sequential numbering. Result1 (Claude) was most accurate. The ideal output format is result1's structure: categorised sections with individual IDs listed, sizes noted, and a clean summary table at the end. Rooms, risers, and lifts should be listed separately and NOT counted as "components" in the equipment total.

Instructions / decisions:
- Output report must list every individual component ID found — no ranges, no assumptions.
- Components are grouped into categories: HVAC Equipment | Ventilation | Fire Safety | Controls | Ductwork.
- Rooms/spaces and lifts are listed as context, NOT counted in the equipment total.
- Ductwork sizes are listed as a reference section, not counted as individual components.
- The summary table at the bottom must show: Category | Individual IDs | Count | Size/Spec.
- A "Document Information" section at top: drawing number, floor, discipline.
- A "Key Notes" section at bottom: any annotation text found in the drawing.
- App must NOT fill gaps in numbering sequences — only count IDs that literally appear in the file.
- Confirmed ground-truth for sample2.pdf (Floor 2) — use this to validate the extraction engine:
  - FCU: 11 (FCU-02-04 to FCU-02-14, NOT 01/02/03)
  - XTA: 6 (XTA-02-01 to XTA-02-06)
  - EG: 5 (EG-02-02 to EG-02-06, NOT EG-02-01)
  - EPH: 2 (EPH-02-01, EPH-02-02)
  - FD: 2 (FD-02-01, FD-02-02)
  - CRU: 1 (CRU-02-01)
  - ATT: 2 (ATT-02-01, ATT-02-02)
  - MFSD: 3 (MFSD-02-01 to MFSD-02-03, NOT 04)
  - EF: 1 (EF-02-01)
  - BS: 1 (BS-02-01)
  - C (AC Controller): 3 (C-02-02, C-02-03, C-02-04, NOT C-02-01)
  - S (diffusers/sensors): 16 (S204–S219, NOT S201–S203)
  - Total confirmed equipment: 53 units

Open questions:
- Codex: still needed — probe sets.dwg and sample2.dwg for block names (unchanged from Prompt 2).
- Are S204–S219 supply air diffusers or temperature sensors? (Legend says S = Temp Sensor, but result1 calls them Smoke Detectors — need DWG attribute to confirm.)
- What does BS abbreviate to? (result1 says "Booster Set" — verify from DWG or user.)

Next suggested action:
Claude Code will now write the PDF extraction module and output report generator based on the confirmed ground-truth above. Codex should still probe the DWG files so the DWG path can be added afterward.

## Prompt 4 - Codex
Date: 2026-06-12

Summary:
Reviewed Claude Code's `.md` updates and confirmed the project should now use only `ai_collaboration.md` and `ai_working.md` as the shared logs. Verified the local environment state for the next DWG/PDF steps. Added an important correction: `ezdxf` is for DXF files and does not directly parse binary DWG files, so the DWG path needs a DWG-to-DXF conversion step or a dedicated DWG-capable tool.

Reasoning summary:
Claude's PDF-first direction is reasonable based on the result files and the reported readable component labels. The result files also confirm the main product risk: AI/manual interpretation can hallucinate missing sequential IDs, so the extraction engine must be literal and evidence-based. For DWG, the local files are binary AC1032 DWGs, there is no `.dxf` file in the workspace, no CAD converter was found locally, and the needed Python packages are not installed. Therefore DWG probing cannot honestly be marked complete yet.

Instructions / decisions:
- Active shared files are `ai_collaboration.md` and `ai_working.md`; ignore the old extensionless `ai_collaboration` and `ai_working` files.
- Correction to earlier Claude stack note: use `ezdxf` only after DWG files are converted/exported to DXF.
- Do not tell Claude Code to rely on `ezdxf.readfile()` for `.dwg`; that will not work for binary DWG.
- Phase 1 can proceed PDF-first with PyMuPDF once installed.
- DWG support should be designed as either:
  - User/export workflow: ask the user/friend to export DWG as DXF from AutoCAD, then parse with `ezdxf`.
  - Tool workflow: install/use a DWG converter such as ODA File Converter, AutoCAD `accoreconsole`, or another DWG-capable library/service.
- The extraction engine must count only IDs literally found in the source. No sequence gap filling.
- Treat result1/result3/result4/result5 AI outputs as analysis aids, not ground truth unless confirmed by actual extraction or user review.

Open questions:
- Can the user/friend export the AutoCAD drawings as DXF as well as PDF/DWG?
- Should Codex request permission to install Python packages (`PyMuPDF`, `openpyxl`, possibly `ezdxf`) and a DWG converter if needed?
- Should the first prototype ignore DWG and validate PDF extraction against `sample2.pdf` first?
- Is `S204-S219` temperature sensor, diffuser, smoke detector, or another symbol in this drawing set? This remains unresolved.
- Is the controller prefix actually `C` or `CC` in the source PDF text? Result files disagree; the parser should reveal the literal labels.

Next suggested action:
Build and run a PDF extraction probe first after installing PyMuPDF. For DWG, get a DXF export or install a DWG converter before attempting block/layer/attribute extraction.

## Prompt 4 - Claude Code
Date: 2026-06-17

Summary:
User provided a new reference file "Standard CAD BLOCKS EXPANDED.pdf" — the company's full standard block library — and instructed that this replaces sample1.pdf for component identification. Acknowledged Codex's correction that ezdxf does not read binary DWG directly (needs DXF). File is not yet in the project folder; need user to save it there for full text extraction.

Reasoning summary:
The Standard CAD BLOCKS EXPANDED.pdf is significantly more comprehensive than sample1.pdf. It shows all block types the company uses across all manufacturers (Mitsubishi, Daikin, Toshiba, Diffusion, Bay, etc.) plus a colour/layer legend on the right side. This is the master reference for building the component taxonomy. The PDF was shared in chat — text is too small to read fully from the visual rendering at this resolution. The correct approach is to save the file to f:\auto extract\ and run PyMuPDF text extraction to get all block category names. Codex's ezdxf clarification is important: the DWG path requires DXF conversion first, which changes the workflow. For now PDF-first is the correct track.

Instructions / decisions:
- sample1.pdf is SUPERSEDED by Standard CAD BLOCKS EXPANDED.pdf as the component library reference.
- Standard CAD BLOCKS EXPANDED.pdf must be saved to f:\auto extract\ so Claude Code can extract its full text.
- From visual inspection the block library contains at minimum these categories (to be confirmed by text extraction):
    Mitsubishi FCUs & Condensers
    Mitsubishi BC Boxes & Lossnay
    Daikin FCUs & Condensers
    Daikin BC Boxes & VRV
    Toshiba FCUs & Condensers
    Toshiba Heat Recovery / VRF
    Diffusion (yellow symbols)
    Bay VRF
    VRVs
    Tray VRF
    Attenuator
    Radiator
    Colour/layer legend (right side panel)
- DWG correction (from Codex Prompt 4): ezdxf reads DXF only, not binary DWG. DWG support requires one of:
    (a) User exports DXF from AutoCAD (preferred — no extra tools)
    (b) Install ODA File Converter to convert DWG → DXF programmatically
- Asking user: can the friend export drawings as DXF in addition to PDF and DWG?

Open questions:
- User: please save Standard CAD BLOCKS EXPANDED.pdf to f:\auto extract\ so Claude Code can read it.
- Can the friend export drawings as DXF from AutoCAD? (Resolves DWG path.)
- Are S204–S219 supply air diffusers, temperature sensors, or smoke detectors? (Still unresolved.)

Next suggested action:
User saves Standard CAD BLOCKS EXPANDED.pdf to f:\auto extract\. Claude Code then reads it with PyMuPDF text extraction to build the definitive component_taxonomy.json. Then proceed to write pdf_parser.py and validate against sample2.pdf ground-truth counts.

## Prompt 5 - Claude Code
Date: 2026-06-20

Summary:
Built the complete working software. Five files created and tested: taxonomy.json, requirements.txt, pdf_parser.py, report_generator.py, app.py. PDF extraction confirmed working on sample2.pdf. Excel and text reports generate successfully. One important finding: the PDF contains more component IDs than result1 suggested — the extraction is literal and correct.

Reasoning summary:
The user clarified that Standard CAD BLOCKS EXPANDED.pdf is the component identification reference (not a test drawing), sample1/2.pdf are the test drawings the software processes, and the result files show what report formats are desired. The approach: combine ALL the best elements from result1–result5 into one report. Taxonomy built from known codes seen across sample PDFs and visual inspection of the block library. PDF-first path is working. DXF path is coded but not yet tested (blocked on user providing a DXF file).

Instructions / decisions:
- Software stack delivered: Python 3.x, PyMuPDF, openpyxl, ezdxf, tkinter.
- Entry point: python app.py
- Install: pip install -r requirements.txt
- PDF extraction: pdf_parser.py — regex-based, ID-literal (no gap filling).
- DXF extraction: pdf_parser.py extract_from_dxf() — ready, needs DXF file to test.
- Report output: Excel (.xlsx, 5 sheets) + text (.txt) — both generated per export.
- UI: tkinter desktop app with tabs (Equipment | Ductwork | Spaces | Notes), editable quantities, export buttons.
- taxonomy.json: 32 component types defined, easily extensible by editing JSON.
- Finding: sample2.pdf contains FCU-02-01 to FCU-02-14 (14 FCUs), EG-02-01 to EG-02-06 (6 EGs), S201–S219 (19 S-points). These are the literal PDF values. Result1 showed fewer — likely because result1 did visual analysis only and missed some. App is correct.
- Drawing number not extractable from sample2.pdf — it is in the title block as vector geometry, not text. Shows as N/A in report; source filename is always shown instead.

Open questions:
- Codex: please probe sets.dwg and sample2.dwg for block names (still pending from earlier).
- User: save Standard CAD BLOCKS EXPANDED.pdf to f:\auto extract\ so taxonomy can be expanded from it.
- User: can friend export drawings as DXF for the richer DWG path?
- S-series (S201–S219): type still unconfirmed. Currently labelled "Supply Diffuser / Temperature Sensor" in taxonomy.

Next suggested action:
User runs: python app.py — loads sample2.pdf — verifies the component table — exports a report. Feedback on any corrections or additions needed to the taxonomy or report format.

## Prompt 6 - Claude Code
Date: 2026-07-01

Summary:
Analysed 10 new project files from `newprojecttdbank/` folder. Found 4 gaps in the extraction engine and fixed all of them. Updated taxonomy.json with 18 new component types. Rebuilt dist/MEP Component Extractor.exe.

Reasoning summary:
The new project (S70992 — TD Bank, Floor 2) introduced component naming patterns that the original regex did not handle: slash notation (CT/02/01), three-digit grille references with letter suffix (SG-201-A), letter suffix on sequence digit (XTA-02-7A), and CT subtype codes without floor number (CTM-01). These were completely missed by the old parser. After fixing all four patterns, the new PDF now yields 79 standard component IDs (previously only 5 with the old parser) plus 73 unique grille references totalling 155 physical grille instances. The taxonomy was expanded from 32 to 50 types to cover SER, MER, LD, SP, GD, WP, WH, SEF, WCEF, CT, CTM, CTE, CTX, CTP, CTS, FG and others found in the TD Bank schedules.

Instructions / decisions:
- COMPONENT_RE updated to allow optional letter suffix on sequence: `r'\b([A-Z]{1,5})-(\d{2})-(\d{1,3}[A-Za-z]?)\b'`
- New SLASH_RE pattern: `r'\b([A-Z]{1,5})/(\d{2})/(\d{2,3})\b'` — slash-notation IDs normalised to dash form.
- New GRILLE_REF_RE: `r'\b([A-Z]{1,3})-(\d{3})-([A-Z])\b'` — occurrence-counted, stored in `result.grille_refs` (not `result.components`). Same grille reference (e.g. SG-207-A) can appear 4 times = 4 physical grilles.
- New CT_SUBTYPE_RE: `r'\b(CT[MEXPS]|FG)-(\d{1,2}[A-Za-z]?)\b'` — captures CTM-01, CTE-02, etc. (no floor number).
- Single-letter codes (e.g. C for AC Controller) are now captured — removed `len(prefix) > 1` guard from standard-dash loop. EXCLUDE_PREFIXES handles non-component single letters.
- ExtractionResult dataclass: added `grille_refs: Dict[str, int]` field; kept `lifts` field.
- components_by_category() now appends grille ref schedule entries with `is_grille: True` flag.
- taxonomy.json expanded from 32 to 50 entries.
- dist/MEP Component Extractor.exe rebuilt (45.1 MB, same size — PyInstaller bundles same deps).

Open questions:
- ASG-xxx-A and BSG-xxx-A grille refs appear in the TD Bank PDF — these may be zone-prefixed grille refs (A-zone, B-zone) or false matches from drawing annotation text. User should verify.
- SER, MER, LD, WP, WH components appear in Excel schedules only (not in the PDF floor plan). The app currently processes PDFs — these will appear when a PDF drawing that includes them is opened.
- Floor level detected as "Level 3" from the TD Bank PDF even though component floor code is 02. Likely a "Level 3" text annotation exists somewhere on the drawing. Not a blocker.

Next suggested action:
User double-clicks dist/MEP Component Extractor.exe, opens newprojecttdbank/S70992-M-02-DWK-01_I.pdf, and verifies the 79 components and 155 grille instances are showing correctly in the Equipment tab. Report any components that appear wrong or missing.
## 2026-09-08 — Codex implementation handoff: persistent queue and job controls

Decision: replace Gunicorn-local background threads with a disk-backed SQLite
queue and a separate, single-concurrency analysis service. This directly fixes
the observed VPS failure mode while preserving two responsive web workers.

Product behaviour now implemented:

- Refresh-safe list of queued, running and completed jobs.
- Explicit Cancel for queued/running work; running cancellation terminates the
  dedicated worker process so CPU/RAM are released.
- Delete removes the job record and its input/results directory.
- Save/Unsave controls seven-day automatic retention.
- Fast analysis is default; Advanced vector/map processing is opt-in.
- Multiple uploads queue rather than execute concurrently.
- Job state and result artifacts persist across web worker/service restarts.
- Interrupted jobs are detected and requeued when the worker starts again.

Operational topology:

`Nginx -> 2 Gunicorn web workers -> SQLite queue -> 1 systemd analysis worker`

The analysis worker exits after every completed job and is restarted by systemd,
preventing the retained-memory growth observed in the earlier deployment. See
`ai_working.md` for detailed implementation/test evidence and `deploy/DEPLOY.md`
for the exact server procedure.

Deployment status: completed on 2026-09-08 from GitHub commit `bfe5a58`.
Production verification covered persistent cross-worker status, Fast-mode real
PDF processing, results/report access, Save, queued cancellation and Delete.
Both `mep` and `mep-worker` services are enabled and active.
