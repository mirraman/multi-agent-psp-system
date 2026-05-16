# Multi-Agent PSP System

End-to-end multi-agent platform for protein structure prediction, model synthesis, and binding-pocket analysis.

The system orchestrates multiple predictors (ESMFold, Modal/ColabFold path, AlphaFold DB lookup), compares outcomes, chooses a best structure, and runs fpocket-based pocket detection for drug-discovery-oriented analysis.

## What This Project Does

- Exposes a FastAPI backend for submitting protein jobs and tracking results.
- Uses SPADE agents (XMPP messaging) for modular pipeline orchestration.
- Uses Celery + Redis for asynchronous ESMFold predictions.
- Stores jobs, logs, datasets, and outputs in PostgreSQL.
- Detects pockets with fpocket and computes pocket-level quality signals.
- Supports single jobs, dataset batch jobs (FASTA), and disease-driven job batches.

## Architecture Overview

Main runtime components:

- API service: FastAPI app at `backend/app/main.py`
- Agent runtime: `backend/app/AgentRunner.py`
- Agents:
	- `CoordinatorAgent`: workflow orchestration and fallback handling
	- `DataAgent`: UniProt/PDB/AlphaFold DB/Open Targets data collection
	- `PspAgent`: ESMFold via Celery task queue
	- `ModalAgent`: Modal/ColabFold prediction path
	- `ProcessingAgent`: metrics extraction and model processing
	- `AnalysisAgent`: model comparison (including RMSD-oriented analysis)
	- `SynthesisAgent`: best-model selection logic
	- `PocketAgent`: fpocket execution and consensus pocket scoring
	- `OutputAgent`: final output packaging
- Infra services (Docker Compose): PostgreSQL, Redis, XMPP (Prosody), API, Agents, Celery worker.

## Repository Structure

Top-level layout:

- `backend/` core application, Docker setup, scripts, tests
- `backend/app/` FastAPI app, agents, utilities
- `backend/scripts/` smoke tests, evaluation helpers, parsing/extraction scripts
- `backend/tests/` unit and integration tests
- `backend/data/` benchmark and generated outputs
- `tmp_fpocket/` vendored fpocket sources/build artifacts
- `xmpp/` Prosody configuration
- `.cursor/plan/` thesis execution and validation planning

## API Endpoints

Implemented in `backend/app/main.py`.

Core job endpoints:

- `POST /jobs` create a job (accession, sequence/FASTA, or disease batch)
- `GET /jobs/{job_id}` get job metadata/status
- `GET /jobs/{job_id}/logs` get structured pipeline logs
- `GET /jobs/{job_id}/result` get full result for completed jobs

Versioned aliases:

- `POST /v1/jobs`
- `GET /v1/batches/{batch_id}`

Dataset endpoints:

- `POST /datasets` upload FASTA or inline FASTA text to create batch jobs
- `GET /datasets/{dataset_id}` aggregate dataset status
- `GET /datasets/{dataset_id}/jobs` list dataset jobs
- `GET /datasets/{dataset_id}/report` aggregated completed-result summary

Monitoring and validation:

- `GET /metrics` live metrics snapshot
- `GET /dashboard` dashboard HTML
- `POST /validate` run validation against known targets
- `GET /validate` fetch latest cached validation report

Backward-compatible deprecated endpoints:

- `POST /submit/{input_value}`
- `GET /status/{accession}`

## Data and Persistence

The app auto-creates PostgreSQL tables on startup via `backend/app/utils/db.py`.

Key tables include:

- `tasks`
- `job_logs`
- `datasets`
- `protein_results`
- `proteins`
- `aggregates`
- `processed`

## Requirements

Main Python dependencies are declared in:

- `backend/requirements.txt`
- `backend/requirements-dev.txt`

Core stack includes:

- FastAPI, Uvicorn
- SQLAlchemy (async), asyncpg
- Celery, Redis
- SPADE
- BioPython
- requests
- modal

## Quick Start (Docker Compose)

1. Go to the backend folder:

```powershell
cd backend
```

2. Create a local env file (Compose requires `POSTGRES_PASSWORD`; do not commit `.env`):

```powershell
copy .env.example .env
# Edit .env: replace all placeholders (POSTGRES_*, DATABASE_URL, etc.) with your own values.
```

3. (Optional) Export Modal credentials if you want Modal/ColabFold path enabled:

```powershell
$env:MODAL_TOKEN_ID="your_token_id"
$env:MODAL_TOKEN_SECRET="your_token_secret"
```

4. Start all services:

```powershell
docker compose up --build
```

5. Open API docs:

- `http://localhost:8000/docs`

6. Submit a test job:

```json
POST /jobs
{
	"type": "protein_analysis",
	"accession": "P01308"
}
```

7. Track result:

- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/logs`
- `GET /jobs/{job_id}/result`

## Local Development (Without Docker)

You can run API/agents/worker directly, but you must provide:

- PostgreSQL
- Redis
- XMPP server (Prosody)

Then set environment variables (minimum):

- `DATABASE_URL`
- `REDIS_URL`
- `XMPP_DOMAIN`
- `XMPP_PASSWORD`
- `XMPP_AUTO_REGISTER`

Optional behavior flags:

- `ENABLE_MODAL` (set `1` to enable Modal route)
- `MODAL_MIN_SEQUENCE_LENGTH` (default routing threshold is 400)
- `ALPHAFOLD_MIN_CONFIDENCE`
- `EXPERIMENTAL_PREFERRED_RESOLUTION_A`

## Testing

Pytest config is in `backend/pytest.ini`.

Current test files:

- `backend/tests/test_main.py`
- `backend/tests/test_fasta_parser.py`
- `backend/tests/test_fpocket_runner.py`
- `backend/tests/test_fpocket_integration.py`
- `backend/tests/test_pocket_agent.py`

Run tests:

```powershell
cd backend
pytest -q
```

Run integration tests only:

```powershell
cd backend
pytest -m integration -q
```

Note: integration tests require `fpocket` available on PATH and sample input data present.

## Useful Scripts

Inside `backend/scripts/`:

- `e2e_smoke.ps1` full-stack smoke test against running API
- `check_status.py` quick polling utility for recent job IDs
- `eval_run.py` benchmark-like scripted run on a fixed protein set
- `extract_metrics.py` post-process raw evaluation output
- `collect_results.py`, `parse_results.py`, `fetch_results.py` result processing helpers

## Evaluation and Thesis Validation

Planned evaluation strategy is documented in:

- `.cursor/plan/thesis-validation-plan.md`

Highlights:

- Compare 4 configurations: ESMFold, ColabFold, AlphaFold DB, ensemble pipeline
- Benchmark on CASP/CAMEO + thesis targets
- Metrics: RMSD, confidence, runtime, pocket quality
- Statistical analysis with significance testing and effect sizes

## Current Maturity

This codebase is in advanced prototype / research-system stage:

- Pipeline and API are implemented and operationally structured.
- Core fallback and synthesis logic is implemented.
- Evaluation helpers and tests exist.
- Further hardening is still needed for production-grade operation (expanded tests, stricter reproducibility, and deployment/security hardening).

## Troubleshooting

Common checks:

- API not reachable: ensure `api` container is up and port `8000` is mapped.
- Jobs stuck queued: verify agents are running and DB connection is healthy.
- ESMFold missing results: verify Celery worker and Redis are healthy.
- No pockets: verify fpocket binary is available in runtime image.
- Modal route not used: confirm `ENABLE_MODAL=1` and credentials are present.

## License and Academic Use

This project is designed as a diploma thesis / research validation platform for multi-model protein structure pipeline evaluation.

If you publish results, include:

- Exact benchmark target list
- Runtime configuration
- Statistical methodology
- Reproducibility artifacts (raw outputs + scripts)
