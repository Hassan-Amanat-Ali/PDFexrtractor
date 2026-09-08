"""Process one queued analysis and exit so systemd can release all job memory."""

from __future__ import annotations

import json
import logging
import os
import pickle
import signal
import sys
import time
import traceback

from job_store import (artifact_path, claim_next_job, cleanup_expired, get_job,
                       recover_stale_running, update_job)
from ml_detector import MLResult, detect_components_ml
from pdf_parser import ExtractionResult, PYMUPDF_AVAILABLE, extract_from_pdf, total_count
from result_combiner import CombinedResult, combine_results
from vector_analyzer import PIL_AVAILABLE, VectorResult, analyze_pdf_vectors, render_page_map

HERE = os.path.dirname(os.path.abspath(__file__))
DXF_PATH = os.path.join(HERE, "sets.dxf")
TAXONOMY_PATH = os.path.join(HERE, "taxonomy.json")
RETENTION_DAYS = int(os.environ.get("MEP_RETENTION_DAYS", "7"))
POLL_SECONDS = float(os.environ.get("MEP_WORKER_POLL_SECONDS", "2"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mep-worker")
current_job_id: str | None = None


def _stop(_signum, _frame) -> None:
    if current_job_id:
        job = get_job(current_job_id)
        if job and job["status"] == "running":
            update_job(current_job_id, status="cancelled", stage="Cancelled",
                       completed_at=time.time(), worker_pid=None)
    raise SystemExit(0)


def _stage(job_id: str, number: int, message: str) -> None:
    update_job(job_id, stage_num=number, stage=message)


def process(job: dict) -> None:
    global current_job_id
    current_job_id = job["id"]
    job_id = job["id"]
    input_path = artifact_path(job_id, "input" + job["extension"])
    try:
        _stage(job_id, 1, "Stage 1 / 4 - Extracting text from drawing")
        if job["extension"] == ".pdf":
            s1: ExtractionResult = extract_from_pdf(input_path)
        else:
            from pdf_parser import extract_from_dxf
            s1 = extract_from_dxf(input_path)
        log.info("[%s] Stage 1 complete - %d components", job_id[:8], total_count(s1))
        s2 = VectorResult(source_file=os.path.basename(input_path))
        s3 = MLResult(source_file=os.path.basename(input_path))
        if job["mode"] == "advanced" and job["extension"] == ".pdf" and PYMUPDF_AVAILABLE:
            _stage(job_id, 2, "Stage 2 / 4 - Analysing vector paths")
            s2 = analyze_pdf_vectors(input_path,
                dxf_path=DXF_PATH if os.path.isfile(DXF_PATH) else None)
            log.info("[%s] Stage 2 complete - %d clusters", job_id[:8],
                     len(s2.labelled_clusters) + len(s2.unlabelled_clusters))
            _stage(job_id, 3, "Stage 3 / 4 - Running ML symbol detection")
            s3 = detect_components_ml(input_path)
        _stage(job_id, 4, "Stage 4 / 4 - Combining results")
        s4: CombinedResult = combine_results(s1, s2, s3)
        maps = []
        if job["mode"] == "advanced" and PIL_AVAILABLE and job["extension"] == ".pdf":
            _stage(job_id, 4, "Rendering annotated maps")
            with open(TAXONOMY_PATH, encoding="utf-8") as handle:
                taxonomy = json.load(handle)
            for stage, show_unlabelled, label in ((1, False, "Stage 1"), (2, True, "Stage 2")):
                image = render_page_map(input_path, s2, taxonomy, page_num=0,
                    show_unlabelled=show_unlabelled, stage_label=label)
                if image is not None:
                    image.save(artifact_path(job_id, f"map-{stage}.png"), "PNG")
                    image.close()
                    maps.append(stage)
        with open(artifact_path(job_id, "results.pkl"), "wb") as handle:
            pickle.dump({"s1": s1, "s2": s2, "s3": s3, "s4": s4, "maps": maps}, handle)
        update_job(job_id, status="complete", stage="Complete", stage_num=5,
                   completed_at=time.time(), worker_pid=None, error=None)
        log.info("[%s] Analysis complete", job_id[:8])
    except SystemExit:
        raise
    except Exception as exc:
        update_job(job_id, status="failed", stage="Analysis failed", error=str(exc),
                   completed_at=time.time(), worker_pid=None)
        log.error("[%s] Analysis failed: %s\n%s", job_id[:8], exc, traceback.format_exc())
    finally:
        current_job_id = None


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    cleanup_expired(RETENTION_DAYS)
    recovered = recover_stale_running()
    if recovered:
        log.warning("Recovered %d interrupted job(s)", recovered)
    while True:
        job = claim_next_job(os.getpid())
        if job:
            process(job)
            return 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
