"""
MEP Component Extractor — Flask web application.

Start:  python web_app.py
Prod:   gunicorn -w 2 -b 127.0.0.1:5000 web_app:app

Credentials are set via environment variables:
    MEP_USER       (default: admin)
    MEP_PASSWORD   (default: changeme  — CHANGE THIS on the server)
    MEP_SECRET_KEY (random bytes used for session signing — set a fixed value for prod)
"""

from __future__ import annotations
import io
import json
import logging
import os
import sys
import threading
import time
import traceback
import uuid
from collections import defaultdict
from functools import wraps

from flask import (
    Flask, abort, redirect, render_template, request,
    send_file, session, url_for, jsonify,
)

# ── project path so imports resolve from the same directory as this file ──────
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from pdf_parser import (
    ExtractionResult,
    PYMUPDF_AVAILABLE,
    components_by_category,
    extract_from_pdf,
    total_count,
)
from report_generator import generate_excel, generate_text_report
from vector_analyzer import (
    PIL_AVAILABLE,
    VectorResult,
    analyze_pdf_vectors,
    render_page_map,
)
from ml_detector import MLResult, detect_components_ml
from result_combiner import CombinedResult, combine_results

# ── app setup ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = os.environ.get('MEP_SECRET_KEY') or os.urandom(32)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# ── taxonomy ──────────────────────────────────────────────────────────────────

_TAXONOMY_PATH = os.path.join(_HERE, 'taxonomy.json')

def _load_taxonomy() -> dict:
    if os.path.isfile(_TAXONOMY_PATH):
        with open(_TAXONOMY_PATH, encoding='utf-8') as fh:
            return json.load(fh)
    return {}

TAXONOMY = _load_taxonomy()

CATEGORY_ORDER = [
    'HVAC Equipment', 'Ventilation', 'Fire Safety',
    'Controls & Sensors', 'Controls', 'Pipework', 'Heating', 'Other',
]

CATEGORY_COLOURS = {
    'HVAC Equipment':     '#D6E4F0',
    'Ventilation':        '#D5F5E3',
    'Fire Safety':        '#FADBD8',
    'Controls':           '#FDEBD0',
    'Controls & Sensors': '#FEF9E7',
    'Pipework':           '#E8DAEF',
    'Heating':            '#F9EBEA',
    'Other':              '#F2F3F4',
}

# ── upload directory ──────────────────────────────────────────────────────────

UPLOAD_DIR = os.path.join(_HERE, 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

DXF_PATH = os.path.join(_HERE, 'sets.dxf')

# ── auth ──────────────────────────────────────────────────────────────────────

MEP_USER     = os.environ.get('MEP_USER', 'admin')
MEP_PASSWORD = os.environ.get('MEP_PASSWORD', 'changeme')


def _login_required(f):
    @wraps(f)
    def _inner(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return _inner


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if (request.form.get('username') == MEP_USER and
                request.form.get('password') == MEP_PASSWORD):
            session.permanent = True
            session['logged_in'] = True
            session['username'] = request.form.get('username')
            return redirect(request.args.get('next') or url_for('index'))
        error = 'Invalid username or password.'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ── job store ─────────────────────────────────────────────────────────────────

jobs: dict[str, dict] = {}


def _new_job(filename: str) -> dict:
    return {
        'status':    'running',   # running | done | error
        'stage':     'Starting…',
        'stage_num': 0,           # 0-5
        'filename':  filename,
        'created':   time.time(),
        's1': None, 's2': None, 's3': None, 's4': None,
        'error': None,
        'maps': {},               # int stage → PIL Image
    }


# ── background analysis ───────────────────────────────────────────────────────

def _run_analysis(job_id: str, input_path: str, ext: str) -> None:
    job = jobs[job_id]
    try:
        # Stage 1 — text extraction
        job['stage'] = 'Stage 1 / 4  —  Extracting text from drawing…'
        job['stage_num'] = 1
        if ext == '.pdf':
            s1: ExtractionResult = extract_from_pdf(input_path)
        else:
            from pdf_parser import extract_from_dxf
            s1 = extract_from_dxf(input_path)
        job['s1'] = s1
        log.info('[%s] Stage 1 complete — %d components', job_id[:8], total_count(s1))

        # Stage 2 — vector / DXF analysis
        job['stage'] = 'Stage 2 / 4  —  Analysing vector paths and DXF fingerprints…'
        job['stage_num'] = 2
        if ext == '.pdf' and PYMUPDF_AVAILABLE:
            s2: VectorResult = analyze_pdf_vectors(
                input_path,
                dxf_path=DXF_PATH if os.path.isfile(DXF_PATH) else None,
            )
        else:
            s2 = VectorResult(source_file=os.path.basename(input_path))
        job['s2'] = s2
        log.info('[%s] Stage 2 complete — %d clusters', job_id[:8],
                 len(s2.labelled_clusters) + len(s2.unlabelled_clusters))

        # Stage 3 — ML detection
        job['stage'] = 'Stage 3 / 4  —  Running ML symbol detection…'
        job['stage_num'] = 3
        if ext == '.pdf' and PYMUPDF_AVAILABLE:
            s3: MLResult = detect_components_ml(input_path)
        else:
            s3 = MLResult(source_file=os.path.basename(input_path))
        job['s3'] = s3

        # Stage 4 — combine
        job['stage'] = 'Stage 4 / 4  —  Combining all results…'
        job['stage_num'] = 4
        s4: CombinedResult = combine_results(s1, s2, s3)
        job['s4'] = s4

        # Render map images
        job['stage'] = 'Rendering annotated maps…'
        if PIL_AVAILABLE and ext == '.pdf':
            for stg, show_unl, lbl in [(1, False, 'Stage 1'), (2, True, 'Stage 2')]:
                img = render_page_map(
                    input_path, s2, TAXONOMY,
                    page_num=0,
                    show_unlabelled=show_unl,
                    stage_label=lbl,
                )
                if img is not None:
                    job['maps'][stg] = img

        job['status'] = 'done'
        job['stage'] = 'Complete'
        job['stage_num'] = 5
        log.info('[%s] Analysis complete', job_id[:8])

    except Exception as exc:
        job['status'] = 'error'
        job['error'] = str(exc)
        log.error('[%s] Analysis failed: %s\n%s', job_id[:8], exc, traceback.format_exc())


# ── routes ────────────────────────────────────────────────────────────────────

@app.route('/')
@_login_required
def index():
    return render_template('index.html', username=session.get('username', ''))


@app.route('/upload', methods=['POST'])
@_login_required
def upload():
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify(error='No file received.'), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ('.pdf', '.dxf'):
        return jsonify(error='Only PDF and DXF files are supported.'), 400

    job_id  = str(uuid.uuid4())
    job_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    safe_name  = 'input' + ext
    input_path = os.path.join(job_dir, safe_name)
    f.save(input_path)
    log.info('[%s] Saved upload: %s (%d bytes)',
             job_id[:8], f.filename, os.path.getsize(input_path))

    jobs[job_id] = _new_job(f.filename)
    threading.Thread(
        target=_run_analysis, args=(job_id, input_path, ext), daemon=True
    ).start()

    return jsonify(job_id=job_id)


@app.route('/status/<job_id>')
@_login_required
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify(error='Unknown job.'), 404
    return jsonify(
        status=job['status'],
        stage=job['stage'],
        stage_num=job['stage_num'],
        error=job.get('error'),
    )


@app.route('/results/<job_id>')
@_login_required
def results(job_id):
    job = jobs.get(job_id)
    if not job:
        abort(404)

    if job['status'] == 'running':
        return render_template('waiting.html',
                               job_id=job_id,
                               filename=job['filename'])

    if job['status'] == 'error':
        return render_template('error.html',
                               error=job['error'],
                               filename=job['filename'])

    s1: ExtractionResult = job['s1']
    s2: VectorResult     = job['s2']

    # Build grouped component rows for the HTML table
    grouped  = components_by_category(s1, TAXONOMY)
    rows: list[dict] = []
    grand_total = 0

    for cat in CATEGORY_ORDER:
        items = grouped.get(cat, [])
        for item in items:
            rows.append({
                'cat':       cat,
                'colour':    CATEGORY_COLOURS.get(cat, '#F2F3F4'),
                'code':      item.get('code', ''),
                'full_name': item.get('full_name', ''),
                'ids':       item.get('ids', ''),
                'count':     item.get('count', 0),
            })
            grand_total += item.get('count', 0)

    # Unlabelled ATT/XTA from Layer C (vector fingerprint)
    unlab_att_xta = [
        c for c in (s2.unlabelled_clusters if s2 else [])
        if c.fingerprint_code in ('ATT', 'XTA')
    ]

    has_map = bool(job.get('maps'))

    return render_template(
        'results.html',
        job_id=job_id,
        filename=job['filename'],
        rows=rows,
        grand_total=grand_total,
        unlab=unlab_att_xta,
        has_map=has_map,
        taxonomy=TAXONOMY,
        drawing_number=getattr(s1, 'drawing_number', None),
        floor_level=getattr(s1, 'floor_level', None),
        username=session.get('username', ''),
    )


@app.route('/map/<job_id>/<int:stage>')
@_login_required
def serve_map(job_id, stage):
    job = jobs.get(job_id)
    if not job:
        abort(404)
    img = job.get('maps', {}).get(stage)
    if img is None:
        abort(404)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')


@app.route('/positions/<job_id>')
@_login_required
def positions(job_id):
    """Return all component bounding boxes as JSON for client-side highlighting."""
    job = jobs.get(job_id)
    if not job or job['status'] != 'done':
        return jsonify(error='Not ready.'), 404

    s2: VectorResult = job['s2']
    MAP_DPI   = 100
    scale     = MAP_DPI / 72.0   # matches render_page_map dpi=100

    by_code: dict = defaultdict(list)

    for pc in (s2.positioned_components if s2 else []):
        bbox = pc.symbol_bbox or pc.bbox   # prefer actual symbol body
        x0, y0, x1, y1 = bbox
        by_code[pc.component_type].append({
            'id':   pc.component_id,
            'page': pc.page_num,
            'x0':   round(x0 * scale, 1),
            'y0':   round(y0 * scale, 1),
            'x1':   round(x1 * scale, 1),
            'y1':   round(y1 * scale, 1),
        })

    for cl in (s2.unlabelled_clusters if s2 else []):
        code = cl.fingerprint_code or 'Unknown'
        x0, y0, x1, y1 = cl.bbox
        by_code[code].append({
            'id':        f'{code}-unlabelled',
            'page':      cl.page_num,
            'x0':        round(x0 * scale, 1),
            'y0':        round(y0 * scale, 1),
            'x1':        round(x1 * scale, 1),
            'y1':        round(y1 * scale, 1),
            'unlabelled': True,
        })

    return jsonify(scale=scale, components=dict(by_code))


@app.route('/download/<job_id>/<fmt>')
@_login_required
def download(job_id, fmt):
    job = jobs.get(job_id)
    if not job or job['status'] != 'done':
        abort(404)

    job_dir  = os.path.join(UPLOAD_DIR, job_id)
    s1: ExtractionResult = job['s1']
    s4: CombinedResult   = job.get('s4')
    stem = os.path.splitext(job['filename'])[0]

    if fmt == 'excel':
        out_path = os.path.join(job_dir, 'report.xlsx')
        generate_excel(s1, out_path,
                       taxonomy_path=_TAXONOMY_PATH,
                       combined_result=s4)
        return send_file(out_path, as_attachment=True,
                         download_name=f'{stem}_report.xlsx')

    if fmt == 'text':
        out_path = os.path.join(job_dir, 'report.txt')
        generate_text_report(s1, out_path, taxonomy_path=_TAXONOMY_PATH)
        return send_file(out_path, as_attachment=True,
                         download_name=f'{stem}_report.txt')

    abort(400)


# ── dev server ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
