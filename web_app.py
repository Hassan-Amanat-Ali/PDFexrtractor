"""Persistent web frontend for the MEP Component Extractor."""

from __future__ import annotations

import json
import os
import pickle
import signal
import sys
import uuid
from collections import defaultdict
from functools import wraps
from urllib.parse import urljoin, urlparse

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_file, session, url_for)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from job_store import (artifact_path, create_job, delete_job, get_job, init_store,
                       job_dir, list_jobs, queue_position, request_cancel, set_saved)
from pdf_parser import ExtractionResult, components_by_category
from report_generator import generate_excel, generate_text_report
from vector_analyzer import VectorResult

app = Flask(__name__)
app.secret_key = os.environ.get("MEP_SECRET_KEY") or os.urandom(32)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MEP_MAX_UPLOAD_MB", "100")) * 1024 * 1024
MEP_USER = os.environ.get("MEP_USER", "admin")
MEP_PASSWORD = os.environ.get("MEP_PASSWORD", "changeme")
TAXONOMY_PATH = os.path.join(HERE, "taxonomy.json")
with open(TAXONOMY_PATH, encoding="utf-8") as handle:
    TAXONOMY = json.load(handle)

CATEGORY_ORDER = ["HVAC Equipment", "Ventilation", "Fire Safety",
                  "Controls & Sensors", "Controls", "Pipework", "Heating", "Other"]
CATEGORY_COLOURS = {
    "HVAC Equipment": "#D6E4F0", "Ventilation": "#D5F5E3",
    "Fire Safety": "#FADBD8", "Controls": "#FDEBD0",
    "Controls & Sensors": "#FEF9E7", "Pipework": "#E8DAEF",
    "Heating": "#F9EBEA", "Other": "#F2F3F4"}
init_store()


@app.template_filter("datetime")
def format_datetime(timestamp) -> str:
    if not timestamp:
        return ""
    from datetime import datetime
    return datetime.fromtimestamp(float(timestamp)).strftime("%d %b %Y, %H:%M")


def _login_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return function(*args, **kwargs)
    return wrapped


def _owner() -> str:
    return str(session.get("username", ""))


def _safe_next(target: str | None) -> bool:
    if not target:
        return False
    base = urlparse(request.host_url)
    destination = urlparse(urljoin(request.host_url, target))
    return destination.scheme in ("http", "https") and base.netloc == destination.netloc


def _load_results(job_id: str) -> dict:
    path = artifact_path(job_id, "results.pkl")
    if not os.path.isfile(path):
        abort(404)
    with open(path, "rb") as handle:
        return pickle.load(handle)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("username") == MEP_USER and request.form.get("password") == MEP_PASSWORD:
            session.permanent = True
            session["logged_in"] = True
            session["username"] = request.form.get("username")
            target = request.args.get("next")
            return redirect(target if _safe_next(target) else url_for("index"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/healthz")
def healthz():
    return jsonify(status="ok")


@app.route("/")
@_login_required
def index():
    jobs = list_jobs(_owner())
    for job in jobs:
        job["queue_position"] = queue_position(job["id"]) if job["status"] == "queued" else 0
    return render_template("index.html", username=_owner(), jobs=jobs)


@app.route("/upload", methods=["POST"])
@_login_required
def upload():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify(error="No file received."), 400
    extension = os.path.splitext(uploaded.filename)[1].lower()
    if extension not in (".pdf", ".dxf"):
        return jsonify(error="Only PDF and DXF files are supported."), 400
    mode = request.form.get("mode", "fast")
    mode = mode if mode in ("fast", "advanced") else "fast"
    job_id = str(uuid.uuid4())
    os.makedirs(job_dir(job_id), mode=0o750)
    uploaded.save(artifact_path(job_id, "input" + extension))
    create_job(job_id, _owner(), uploaded.filename, extension, mode)
    return jsonify(job_id=job_id, status="queued")


@app.route("/status/<job_id>")
@_login_required
def status(job_id):
    job = get_job(job_id, _owner())
    if not job:
        return jsonify(error="Unknown job."), 404
    return jsonify(status=job["status"], stage=job["stage"], stage_num=job["stage_num"],
                   error=job["error"],
                   queue_position=queue_position(job_id) if job["status"] == "queued" else 0)


@app.route("/results/<job_id>")
@_login_required
def results(job_id):
    job = get_job(job_id, _owner())
    if not job:
        abort(404)
    if job["status"] in ("queued", "running"):
        return render_template("waiting.html", job_id=job_id, filename=job["filename"], username=_owner())
    if job["status"] == "cancelled":
        return render_template("error.html", error="This analysis was cancelled.",
                               filename=job["filename"], username=_owner())
    if job["status"] == "failed":
        return render_template("error.html", error=job["error"], filename=job["filename"], username=_owner())
    if job["status"] != "complete":
        abort(404)
    bundle = _load_results(job_id)
    s1: ExtractionResult = bundle["s1"]
    s2: VectorResult = bundle["s2"]
    grouped = components_by_category(s1, TAXONOMY)
    rows, grand_total = [], 0
    for category in CATEGORY_ORDER:
        for item in grouped.get(category, []):
            ids = item.get("ids", "")
            rows.append({"cat": category, "colour": CATEGORY_COLOURS.get(category, "#F2F3F4"),
                         "code": item.get("code", ""), "full_name": item.get("full_name", ""),
                         "ids": ", ".join(ids) if isinstance(ids, list) else ids,
                         "count": item.get("count", 0)})
            grand_total += item.get("count", 0)
    unlabelled = [cluster for cluster in (s2.unlabelled_clusters if s2 else [])
                  if cluster.fingerprint_code in ("ATT", "XTA")]
    return render_template("results.html", job_id=job_id, filename=job["filename"], rows=rows,
        grand_total=grand_total, unlab=unlabelled, has_map=bool(bundle.get("maps")),
        taxonomy=TAXONOMY, drawing_number=getattr(s1, "drawing_number", None),
        floor_level=getattr(s1, "floor_level", None), username=_owner(), job=job)


@app.route("/map/<job_id>/<int:stage>")
@_login_required
def serve_map(job_id, stage):
    if not get_job(job_id, _owner()) or stage not in (1, 2):
        abort(404)
    path = artifact_path(job_id, f"map-{stage}.png")
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype="image/png")


@app.route("/positions/<job_id>")
@_login_required
def positions(job_id):
    job = get_job(job_id, _owner())
    if not job or job["status"] != "complete":
        return jsonify(error="Not ready."), 404
    s2: VectorResult = _load_results(job_id)["s2"]
    scale, by_code = 100 / 72.0, defaultdict(list)
    for component in s2.positioned_components if s2 else []:
        x0, y0, x1, y1 = component.symbol_bbox or component.bbox
        by_code[component.component_type].append({"id": component.component_id,
            "page": component.page_num, "x0": round(x0 * scale, 1),
            "y0": round(y0 * scale, 1), "x1": round(x1 * scale, 1),
            "y1": round(y1 * scale, 1)})
    return jsonify(scale=scale, components=dict(by_code))


@app.route("/download/<job_id>/<fmt>")
@_login_required
def download(job_id, fmt):
    job = get_job(job_id, _owner())
    if not job or job["status"] != "complete":
        abort(404)
    bundle, stem = _load_results(job_id), os.path.splitext(job["filename"])[0]
    if fmt == "excel":
        path = artifact_path(job_id, "report.xlsx")
        if not os.path.isfile(path):
            generate_excel(bundle["s1"], path, taxonomy_path=TAXONOMY_PATH,
                           combined_result=bundle.get("s4"))
        return send_file(path, as_attachment=True, download_name=f"{stem}_report.xlsx")
    if fmt == "text":
        path = artifact_path(job_id, "report.txt")
        if not os.path.isfile(path):
            generate_text_report(bundle["s1"], path, taxonomy_path=TAXONOMY_PATH)
        return send_file(path, as_attachment=True, download_name=f"{stem}_report.txt")
    abort(400)


@app.route("/jobs/<job_id>/cancel", methods=["POST"])
@_login_required
def cancel_job(job_id):
    job = request_cancel(job_id, _owner())
    if not job:
        abort(404)
    if job.get("worker_pid"):
        try:
            os.kill(int(job["worker_pid"]), signal.SIGTERM)
        except (OSError, ProcessLookupError, PermissionError):
            pass
    return redirect(url_for("index"))


@app.route("/jobs/<job_id>/save", methods=["POST"])
@_login_required
def save_job(job_id):
    job = get_job(job_id, _owner())
    if not job:
        abort(404)
    set_saved(job_id, _owner(), not bool(job["saved"]))
    return redirect(request.referrer or url_for("index"))


@app.route("/jobs/<job_id>/delete", methods=["POST"])
@_login_required
def remove_job(job_id):
    if not delete_job(job_id, _owner()):
        return jsonify(error="Cancel a running job before deleting it."), 409
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
