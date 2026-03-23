import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.utils.db import (
    DatabaseConnection,
    insert_task,
    get_task_by_id,
    get_job_logs,
    get_protein_result,
    get_result_by_task_id,
    insert_dataset,
    get_dataset,
    get_dataset_jobs,
    get_metrics,
    # kept for backward compatibility
    upsert_protein_result,
)
from app.utils.fasta_parser import parse_fasta, is_valid_protein_sequence
from app.utils.validation_set import VALIDATION_TARGETS
from app.utils.validate import validate_pocket, extract_best_predicted_residues

logger = logging.getLogger("psp.main")
LATEST_VALIDATION_REPORT: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://psp:psp@localhost:5432/psp_db"
    )
    try:
        await DatabaseConnection.init(database_url)
        logger.info("Connected to PostgreSQL")
    except Exception as e:
        logger.error(f"Failed to connect to PostgreSQL: {e}")
    yield
    await DatabaseConnection.close()


app = FastAPI(
    title="Multi-Agent PSP System",
    description="Protein Structure Prediction API with drug-discovery pipeline",
    version="2.0.0",
    lifespan=lifespan,
)

# Serve static files (dashboard HTML)
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class JobSubmitRequest(BaseModel):
    type: str = "protein_analysis"
    sequence: Optional[str] = None
    accession: Optional[str] = None
    disease: Optional[str] = None


# ---------------------------------------------------------------------------
# Feature 1: Job Queue API
# ---------------------------------------------------------------------------

def _require_db():
    if DatabaseConnection.engine is None:
        raise HTTPException(status_code=503, detail="Database unavailable")


async def _create_job_impl(body: JobSubmitRequest) -> Dict[str, Any]:
    """
    Submit one or more protein analysis jobs.

    Disease mode: queues top 5 Open Targets accessions as separate tasks (dataset batch).
    """
    _require_db()

    if body.disease:
        from app.utils.open_targets import fetch_disease_targets

        try:
            resolved = fetch_disease_targets(body.disease.strip(), limit=5)
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        targets = resolved["targets"][:5]
        if not targets:
            raise HTTPException(status_code=400, detail="Disease lookup returned no targets")
        dataset_id = await insert_dataset(
            name=resolved.get("disease_name") or body.disease.strip(),
            filename="disease_batch",
            total_jobs=len(targets),
        )
        job_entries: List[Dict[str, Any]] = []
        for t in targets:
            acc = t.get("accession")
            if not acc:
                continue
            jid = await insert_task(
                {
                    "type": body.type,
                    "input_type": "accession",
                    "input_value": acc,
                    "status": "queued",
                    "created_at": datetime.now(),
                    "dataset_id": int(dataset_id),
                }
            )
            job_entries.append(
                {
                    "job_id": int(jid),
                    "accession": acc,
                    "gene_symbol": t.get("gene_symbol"),
                }
            )
        logger.info(
            "Disease batch created: dataset_id=%s jobs=%d",
            dataset_id,
            len(job_entries),
        )
        return {
            "batch_job_id": dataset_id,
            "dataset_id": dataset_id,
            "disease_id": resolved.get("disease_id"),
            "disease_name": resolved.get("disease_name"),
            "job_ids": [e["job_id"] for e in job_entries],
            "jobs": job_entries,
            "status": "queued",
            "input_type": "disease_batch",
            "message": f"Queued {len(job_entries)} protein jobs for disease batch",
        }

    if body.sequence:
        raw = body.sequence.strip()
        if raw.startswith(">"):
            lines = raw.splitlines()
            sequence = "".join(l for l in lines[1:] if not l.startswith(">")).replace(" ", "")
        else:
            sequence = raw
        input_type = "fasta"
        input_value = sequence
    elif body.accession:
        input_type = "accession"
        input_value = body.accession.strip()
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide one of 'disease', 'sequence' (FASTA/amino-acids), or 'accession' (UniProt ID)",
        )

    if not input_value:
        raise HTTPException(status_code=400, detail="Input cannot be empty")

    task_doc = {
        "type": body.type,
        "input_type": input_type,
        "input_value": input_value,
        "status": "queued",
        "created_at": datetime.now(),
    }
    job_id = await insert_task(task_doc)
    logger.info(f"Job created: {job_id} ({input_type}: {input_value[:50]})")

    return {
        "job_id": job_id,
        "status": "queued",
        "input_type": input_type,
        "message": f"Job queued — CoordinatorAgent will pick it up within 5s",
    }


@app.post("/jobs", status_code=201)
async def create_job(body: JobSubmitRequest) -> Dict[str, Any]:
    """
    Submit a protein analysis job.

    Provide either:
    - `sequence`: raw amino-acid string (FASTA without header, or with '>header' prefix)
    - `accession`: UniProt accession ID (e.g. 'P12345')
    - `disease`: disease name — queues top 5 Open Targets accessions as separate jobs (batch dataset)
    """
    return await _create_job_impl(body)


v1_router = APIRouter(prefix="/v1", tags=["v1"])


@v1_router.post("/jobs", status_code=201)
async def create_job_v1(body: JobSubmitRequest) -> Dict[str, Any]:
    """Primary API: same body as POST /jobs (accession, disease, or sequence)."""
    return await _create_job_impl(body)


@v1_router.get("/batches/{batch_id}")
async def get_batch_v1(batch_id: int) -> Dict[str, Any]:
    """Aggregate status for a disease batch (dataset)."""
    _require_db()
    ds = await get_dataset(batch_id)
    if not ds:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")
    if ds.get("created_at") and hasattr(ds["created_at"], "isoformat"):
        ds["created_at"] = ds["created_at"].isoformat()
    jobs = await get_dataset_jobs(batch_id)
    for job in jobs:
        for field in ("created_at", "start_time", "end_time"):
            if job.get(field) and hasattr(job[field], "isoformat"):
                job[field] = job[field].isoformat()
    return {"dataset_id": batch_id, **ds, "jobs": jobs}


app.include_router(v1_router)


@app.get("/jobs/{job_id}")
async def get_job(job_id: int) -> Dict[str, Any]:
    """
    Get job status and metadata.

    Returns: status, start_time, worker_id, retries, execution_time, etc.
    Status values: queued | running | completed | failed
    """
    _require_db()
    job = await get_task_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Serialize datetimes
    for field in ("created_at", "start_time", "end_time"):
        if job.get(field) and hasattr(job[field], "isoformat"):
            job[field] = job[field].isoformat()

    return job


@app.get("/jobs/{job_id}/logs")
async def get_job_log_entries(job_id: int) -> Dict[str, Any]:
    """
    Return structured log entries for a job — one entry per pipeline step.
    """
    _require_db()
    job = await get_task_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    logs = await get_job_logs(job_id)
    for entry in logs:
        if entry.get("timestamp") and hasattr(entry["timestamp"], "isoformat"):
            entry["timestamp"] = entry["timestamp"].isoformat()

    return {"job_id": job_id, "count": len(logs), "logs": logs}


@app.get("/jobs/{job_id}/result")
async def get_job_result(job_id: int) -> Dict[str, Any]:
    """
    Return the full result for a completed job.
    Returns 404 if not completed yet.
    """
    _require_db()
    job = await get_task_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is not completed yet (current status: {job['status']})",
        )

    result = await get_result_by_task_id(job_id)
    if not result:
        # Fallback: try by accession
        result = await get_protein_result(job["input_value"])
    if not result:
        raise HTTPException(status_code=404, detail="Result not yet persisted — try again shortly")

    # Serialize timestamps
    if result.get("timestamp") and hasattr(result["timestamp"], "isoformat"):
        result["timestamp"] = result["timestamp"].isoformat()

    return result


# ---------------------------------------------------------------------------
# Feature 2: Dataset / Batch Processing
# ---------------------------------------------------------------------------

@app.post("/datasets", status_code=201)
async def upload_dataset(
    file: Optional[UploadFile] = File(None),
    fasta_text: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
) -> Dict[str, Any]:
    """
    Upload a FASTA file (or paste FASTA text) to batch-process multiple proteins.

    The system will:
    1. Parse the FASTA into individual proteins
    2. Create a dataset record
    3. Create one job per protein (all queued automatically)
    4. Return the dataset_id to track aggregate progress

    Example FASTA:
        >protein_1
        MKTLLILALAL...
        >protein_2
        AGSTKDL...
    """
    _require_db()

    raw_content: Optional[str] = None
    filename: Optional[str] = None

    if file:
        content_bytes = await file.read()
        try:
            raw_content = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="File must be UTF-8 encoded text")
        filename = file.filename
    elif fasta_text:
        raw_content = fasta_text
        filename = "inline"
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either a 'file' upload or 'fasta_text' form field",
        )

    proteins = parse_fasta(raw_content)
    if not proteins:
        raise HTTPException(
            status_code=422,
            detail="No valid FASTA entries found. Ensure the file starts with '>header' lines.",
        )

    # Filter out invalid sequences
    valid = [(h, n, s) for h, n, s in proteins if is_valid_protein_sequence(s)]
    skipped = len(proteins) - len(valid)

    if not valid:
        raise HTTPException(status_code=422, detail="No protein entries had valid amino-acid sequences")

    dataset_id = await insert_dataset(
        name=name or filename,
        filename=filename,
        total_jobs=len(valid),
    )

    job_ids = []
    for header, prot_name, sequence in valid:
        # Use protein name as input_value for accession-like tracking
        input_value = sequence  # submit raw sequence; CoordinatorAgent handles it
        jid = await insert_task(
            {
                "type": "protein_analysis",
                "input_type": "fasta",
                "input_value": input_value,
                "status": "queued",
                "dataset_id": int(dataset_id),
            }
        )
        job_ids.append({"job_id": jid, "protein_name": prot_name, "sequence_length": len(sequence)})

    logger.info(f"Dataset {dataset_id}: created {len(valid)} jobs from {filename}")

    return {
        "dataset_id": dataset_id,
        "jobs_created": len(valid),
        "skipped_invalid": skipped,
        "job_ids": job_ids,
        "message": f"Dataset queued — {len(valid)} proteins will be processed automatically",
    }


@app.get("/datasets/{dataset_id}")
async def get_dataset_status(dataset_id: int) -> Dict[str, Any]:
    """Aggregate status for a dataset — how many jobs are queued/running/completed/failed."""
    _require_db()
    ds = await get_dataset(dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

    for field in ("created_at",):
        if ds.get(field) and hasattr(ds[field], "isoformat"):
            ds[field] = ds[field].isoformat()

    return ds


@app.get("/datasets/{dataset_id}/jobs")
async def get_dataset_job_list(dataset_id: int) -> Dict[str, Any]:
    """List all jobs in a dataset with their current status."""
    _require_db()
    ds = await get_dataset(dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

    jobs = await get_dataset_jobs(dataset_id)
    for job in jobs:
        for field in ("created_at", "start_time", "end_time"):
            if job.get(field) and hasattr(job[field], "isoformat"):
                job[field] = job[field].isoformat()

    return {"dataset_id": dataset_id, "total": len(jobs), "jobs": jobs}


@app.get("/datasets/{dataset_id}/report")
async def get_dataset_report(dataset_id: int) -> Dict[str, Any]:
    """
    Aggregated report across all completed proteins in a dataset.
    Returns summary stats + per-protein pocket results.
    """
    _require_db()
    ds = await get_dataset(dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id} not found")

    jobs = await get_dataset_jobs(dataset_id)
    completed_jobs = [j for j in jobs if j["status"] == "completed"]

    # Gather results for completed jobs
    protein_summaries = []
    total_pockets = 0
    for job in completed_jobs:
        result = await get_result_by_task_id(job["id"])
        if result:
            pocket_data = result.get("pockets") or {}
            pocket_summary = pocket_data.get("pocket_summary", {}) if isinstance(pocket_data, dict) else {}
            hc = pocket_summary.get("high_confidence", 0)
            total_pockets += hc
            protein_summaries.append(
                {
                    "job_id": job["id"],
                    "accession": result.get("accession"),
                    "execution_time_s": round(job.get("execution_time") or 0, 1),
                    "high_confidence_pockets": hc,
                    "best_model": (result.get("synthesis") or {}).get("best_model"),
                }
            )

    return {
        "dataset_id": dataset_id,
        "dataset_name": ds.get("name"),
        "total_proteins": ds["total_jobs"],
        "completed": len(completed_jobs),
        "failed": ds["job_counts"].get("failed", 0),
        "pending": ds["job_counts"].get("queued", 0) + ds["job_counts"].get("running", 0),
        "total_pockets_found": total_pockets,
        "proteins": protein_summaries,
    }


# ---------------------------------------------------------------------------
# Feature 3: Metrics & Dashboard
# ---------------------------------------------------------------------------

@app.get("/metrics")
async def metrics_endpoint() -> Dict[str, Any]:
    """Return live system metrics for the monitoring dashboard."""
    _require_db()
    return await get_metrics()


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    """Serve the monitoring dashboard HTML page."""
    dashboard_path = os.path.join(
        os.path.dirname(__file__), "static", "dashboard.html"
    )
    if os.path.exists(dashboard_path):
        with open(dashboard_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<html><body><h1>Dashboard not found</h1></body></html>"


# ---------------------------------------------------------------------------
# Feature 4: Validation Against Known Drug-Protein Pairs
# ---------------------------------------------------------------------------

@app.post("/validate")
async def run_validation() -> Dict[str, Any]:
    """
    Validate predicted pockets against known ligand-binding residues.
    For targets with missing results, queue a normal protein job.
    """
    global LATEST_VALIDATION_REPORT
    _require_db()

    evaluated = []
    queued = []

    for target in VALIDATION_TARGETS:
        accession = str(target["accession"])
        known_residues = [int(x) for x in list(target["known_binding_residues"])]
        result = await get_protein_result(accession)

        if not result:
            job_id = await insert_task(
                {
                    "type": "validation_analysis",
                    "input_type": "accession",
                    "input_value": accession,
                    "status": "queued",
                    "created_at": datetime.now(),
                }
            )
            queued.append(
                {
                    "accession": accession,
                    "name": target["name"],
                    "job_id": int(job_id),
                    "status": "queued_for_prediction",
                }
            )
            continue

        predicted_residues = extract_best_predicted_residues(result)
        metrics = validate_pocket(predicted_residues, known_residues, tolerance=2)
        evaluated.append(
            {
                "accession": accession,
                "name": target["name"],
                "known_binding_residues": known_residues,
                "predicted_residues": predicted_residues,
                "metrics": metrics,
            }
        )

    avg_precision = (
        round(sum(x["metrics"]["precision"] for x in evaluated) / len(evaluated), 4)
        if evaluated
        else 0.0
    )
    avg_recall = (
        round(sum(x["metrics"]["recall"] for x in evaluated) / len(evaluated), 4)
        if evaluated
        else 0.0
    )
    avg_f1 = (
        round(sum(x["metrics"]["f1"] for x in evaluated) / len(evaluated), 4)
        if evaluated
        else 0.0
    )

    LATEST_VALIDATION_REPORT = {
        "generated_at": datetime.now().isoformat(),
        "total_targets": len(VALIDATION_TARGETS),
        "evaluated_targets": len(evaluated),
        "queued_targets": len(queued),
        "summary": {
            "avg_precision": avg_precision,
            "avg_recall": avg_recall,
            "avg_f1": avg_f1,
        },
        "evaluated": evaluated,
        "queued": queued,
    }

    return LATEST_VALIDATION_REPORT


@app.get("/validate")
async def get_validation_report() -> Dict[str, Any]:
    """
    Return the latest cached validation report.
    """
    if not LATEST_VALIDATION_REPORT:
        raise HTTPException(
            status_code=404,
            detail="No validation report cached yet. Run POST /validate first.",
        )
    return LATEST_VALIDATION_REPORT


# ---------------------------------------------------------------------------
# Legacy endpoints (backward compatibility — deprecated)
# ---------------------------------------------------------------------------

@app.post("/submit/{input_value}", deprecated=True)
async def submit_job_legacy(input_value: str) -> Dict[str, str]:
    """
    [DEPRECATED] Use POST /jobs instead.
    Submit a protein structure prediction job by accession or FASTA sequence.
    """
    _require_db()
    if not input_value or not input_value.strip():
        raise HTTPException(status_code=400, detail="Input cannot be empty")

    input_type = (
        "fasta"
        if (
            input_value.startswith(">")
            or (input_value and all(c in "ACDEFGHIKLMNPQRSTVWY" for c in input_value.upper()))
        )
        else "accession"
    )

    task_doc = {
        "type": "protein_structure_pipeline",
        "input_type": input_type,
        "input_value": input_value,
        "status": "queued",
        "created_at": datetime.now(),
    }
    job_id = await insert_task(task_doc)
    logger.info(f"[LEGACY] Job registered: {job_id} for {input_type}: {input_value[:50]}")

    return {
        "job_id": job_id,
        "status": "queued",
        "input_type": input_type,
        "message": f"Job submitted to CoordinatorAgent ({input_type})",
    }


@app.get("/status/{accession}", deprecated=True)
async def get_status_legacy(accession: str) -> Dict[str, Any]:
    """[DEPRECATED] Use GET /jobs/{id}/result instead."""
    _require_db()
    result = await get_protein_result(accession)
    if result:
        return {"status": "completed", "data": result}
    return {"status": "processing_or_not_found"}