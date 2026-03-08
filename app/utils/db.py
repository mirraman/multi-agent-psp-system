from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# Schema DDL – created on first startup via _create_tables()
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS datasets (
    id          SERIAL PRIMARY KEY,
    name        TEXT,
    filename    TEXT,
    total_jobs  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status      TEXT NOT NULL DEFAULT 'processing'
);

CREATE TABLE IF NOT EXISTS tasks (
    id              SERIAL PRIMARY KEY,
    type            TEXT NOT NULL DEFAULT 'protein_structure_pipeline',
    input_type      TEXT NOT NULL DEFAULT 'accession',
    input_value     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    start_time      TIMESTAMPTZ,
    end_time        TIMESTAMPTZ,
    worker_id       TEXT,
    retries         INTEGER NOT NULL DEFAULT 0,
    execution_time  DOUBLE PRECISION,
    error_message   TEXT,
    output_path     TEXT,
    dataset_id      INTEGER REFERENCES datasets(id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status     ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_dataset_id ON tasks(dataset_id);

CREATE TABLE IF NOT EXISTS job_logs (
    id        SERIAL PRIMARY KEY,
    task_id   INTEGER NOT NULL REFERENCES tasks(id),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    level     TEXT NOT NULL DEFAULT 'info',
    message   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_logs_task_id ON job_logs(task_id);

CREATE TABLE IF NOT EXISTS proteins (
    id        SERIAL PRIMARY KEY,
    accession TEXT UNIQUE NOT NULL,
    data      JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS protein_results (
    id          SERIAL PRIMARY KEY,
    accession   TEXT UNIQUE NOT NULL,
    task_id     INTEGER REFERENCES tasks(id),
    status      TEXT NOT NULL DEFAULT 'completed',
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    output_path TEXT,
    uniprot     JSONB,
    pdb_files   JSONB,
    metrics     JSONB,
    synthesis   JSONB,
    psp_results JSONB,
    models_used JSONB,
    psp_errors  JSONB,
    analysis    JSONB,
    pockets     JSONB
);

CREATE TABLE IF NOT EXISTS aggregates (
    id        SERIAL PRIMARY KEY,
    accession TEXT UNIQUE NOT NULL,
    data      JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS processed (
    id        SERIAL PRIMARY KEY,
    accession TEXT UNIQUE NOT NULL,
    processed JSONB NOT NULL DEFAULT '{}'
);
"""


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

class DatabaseConnection:
    """Async PostgreSQL connection pool via SQLAlchemy + asyncpg."""

    engine: Optional[AsyncEngine] = None
    _session_factory: Optional[sessionmaker] = None

    @classmethod
    async def init(cls, database_url: str) -> None:
        cls.engine = create_async_engine(
            database_url,
            pool_size=10,
            max_overflow=20,
            echo=False,
        )
        cls._session_factory = sessionmaker(
            cls.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        await cls._create_tables()

    @classmethod
    async def close(cls) -> None:
        if cls.engine:
            await cls.engine.dispose()
        cls.engine = None
        cls._session_factory = None

    @classmethod
    def get_session(cls) -> AsyncSession:
        if cls._session_factory is None:
            raise RuntimeError("Database not initialized")
        return cls._session_factory()

    @classmethod
    async def _create_tables(cls) -> None:
        if cls.engine is None:
            return
        async with cls.engine.begin() as conn:
            await conn.execute(text(_DDL))


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _require_db() -> None:
    if DatabaseConnection.engine is None:
        raise RuntimeError("Database not initialized")


# ---------------------------------------------------------------------------
# Task / Job helpers
# ---------------------------------------------------------------------------

async def insert_task(task: Dict[str, Any]) -> str:
    """Insert a new task row and return its id as a string."""
    _require_db()
    async with DatabaseConnection.get_session() as session:
        result = await session.execute(
            text(
                """
                INSERT INTO tasks (type, input_type, input_value, status, created_at, dataset_id)
                VALUES (:type, :input_type, :input_value, :status, :created_at, :dataset_id)
                RETURNING id
                """
            ),
            {
                "type": task.get("type", "protein_structure_pipeline"),
                "input_type": task.get("input_type", "accession"),
                "input_value": task["input_value"],
                "status": task.get("status", "queued"),
                "created_at": task.get("created_at", datetime.now(timezone.utc)),
                "dataset_id": task.get("dataset_id"),
            },
        )
        row = result.fetchone()
        await session.commit()
        return str(row[0])


async def update_task(task_id: Any, fields: Dict[str, Any]) -> None:
    """Update arbitrary columns on a task row by id."""
    _require_db()
    if not fields:
        return

    set_clauses = ", ".join(f"{k} = :{k}" for k in fields)
    params = {**fields, "task_id": int(task_id)}

    async with DatabaseConnection.get_session() as session:
        await session.execute(
            text(f"UPDATE tasks SET {set_clauses} WHERE id = :task_id"),
            params,
        )
        await session.commit()


async def get_task_by_id(task_id: Any) -> Optional[Dict[str, Any]]:
    """Return a single task row by id, or None."""
    _require_db()
    async with DatabaseConnection.get_session() as session:
        result = await session.execute(
            text(
                """
                SELECT id, type, input_type, input_value, status,
                       created_at, start_time, end_time, worker_id,
                       retries, execution_time, error_message, output_path,
                       dataset_id
                FROM tasks
                WHERE id = :task_id
                """
            ),
            {"task_id": int(task_id)},
        )
        row = result.mappings().fetchone()
        return dict(row) if row else None


async def claim_pending_job() -> Optional[Dict[str, Any]]:
    """
    Atomically claim the oldest queued task (SELECT … FOR UPDATE SKIP LOCKED).
    Sets status → 'running' and records start_time.
    Returns the row as a dict, or None if the queue is empty.
    """
    _require_db()
    import socket
    worker_id = socket.gethostname()

    async with DatabaseConnection.get_session() as session:
        result = await session.execute(
            text(
                """
                SELECT id, type, input_type, input_value, status, created_at,
                       output_path, dataset_id
                FROM tasks
                WHERE status = 'queued'
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """
            )
        )
        row = result.mappings().fetchone()
        if row is None:
            return None

        now = datetime.now(timezone.utc)
        await session.execute(
            text(
                """
                UPDATE tasks
                SET status = 'running', start_time = :start_time, worker_id = :worker_id
                WHERE id = :id
                """
            ),
            {"id": row["id"], "start_time": now, "worker_id": worker_id},
        )
        await session.commit()
        return dict(row)


async def complete_task(task_id: Any, output_path: Optional[str] = None) -> None:
    """Mark a task as completed and record execution_time."""
    _require_db()
    now = datetime.now(timezone.utc)
    async with DatabaseConnection.get_session() as session:
        await session.execute(
            text(
                """
                UPDATE tasks
                SET status = 'completed',
                    end_time = :end_time,
                    output_path = COALESCE(:output_path, output_path),
                    execution_time = EXTRACT(EPOCH FROM (:end_time - start_time))
                WHERE id = :task_id
                """
            ),
            {"task_id": int(task_id), "end_time": now, "output_path": output_path},
        )
        await session.commit()


async def fail_task(task_id: Any, error_message: str) -> None:
    """Mark a task as failed and increment retries counter."""
    _require_db()
    now = datetime.now(timezone.utc)
    async with DatabaseConnection.get_session() as session:
        await session.execute(
            text(
                """
                UPDATE tasks
                SET status = 'failed',
                    end_time = :end_time,
                    error_message = :error_message,
                    retries = retries + 1,
                    execution_time = EXTRACT(EPOCH FROM (:end_time - start_time))
                WHERE id = :task_id
                """
            ),
            {"task_id": int(task_id), "end_time": now, "error_message": error_message},
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Job log helpers
# ---------------------------------------------------------------------------

async def insert_job_log(task_id: Any, message: str, level: str = "info") -> None:
    """Append a structured log entry for a job."""
    _require_db()
    try:
        async with DatabaseConnection.get_session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO job_logs (task_id, timestamp, level, message)
                    VALUES (:task_id, :timestamp, :level, :message)
                    """
                ),
                {
                    "task_id": int(task_id),
                    "timestamp": datetime.now(timezone.utc),
                    "level": level,
                    "message": message,
                },
            )
            await session.commit()
    except Exception:
        pass  # Logs must never crash the pipeline


async def get_job_logs(task_id: Any) -> List[Dict[str, Any]]:
    """Return all log entries for a task, ordered by timestamp."""
    _require_db()
    async with DatabaseConnection.get_session() as session:
        result = await session.execute(
            text(
                """
                SELECT id, task_id, timestamp, level, message
                FROM job_logs
                WHERE task_id = :task_id
                ORDER BY timestamp ASC
                """
            ),
            {"task_id": int(task_id)},
        )
        rows = result.mappings().fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------

async def insert_dataset(name: Optional[str], filename: Optional[str], total_jobs: int) -> str:
    """Create a dataset record and return its id."""
    _require_db()
    async with DatabaseConnection.get_session() as session:
        result = await session.execute(
            text(
                """
                INSERT INTO datasets (name, filename, total_jobs, status)
                VALUES (:name, :filename, :total_jobs, 'processing')
                RETURNING id
                """
            ),
            {"name": name, "filename": filename, "total_jobs": total_jobs},
        )
        row = result.fetchone()
        await session.commit()
        return str(row[0])


async def get_dataset(dataset_id: Any) -> Optional[Dict[str, Any]]:
    """Return dataset info + per-state job counts."""
    _require_db()
    async with DatabaseConnection.get_session() as session:
        result = await session.execute(
            text("SELECT id, name, filename, total_jobs, created_at, status FROM datasets WHERE id = :id"),
            {"id": int(dataset_id)},
        )
        row = result.mappings().fetchone()
        if row is None:
            return None
        ds = dict(row)

        counts_result = await session.execute(
            text(
                """
                SELECT status, COUNT(*) as count
                FROM tasks
                WHERE dataset_id = :id
                GROUP BY status
                """
            ),
            {"id": int(dataset_id)},
        )
        counts = {r["status"]: r["count"] for r in counts_result.mappings().fetchall()}
        ds["job_counts"] = counts

        # Auto-update dataset status
        total = ds["total_jobs"]
        done = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        if done + failed >= total and total > 0:
            final_status = "completed" if failed == 0 else ("failed" if done == 0 else "partial")
            async with DatabaseConnection.get_session() as s2:
                await s2.execute(
                    text("UPDATE datasets SET status = :s WHERE id = :id"),
                    {"s": final_status, "id": int(dataset_id)},
                )
                await s2.commit()
            ds["status"] = final_status

        return ds


async def get_dataset_jobs(dataset_id: Any) -> List[Dict[str, Any]]:
    """Return all tasks for a dataset."""
    _require_db()
    async with DatabaseConnection.get_session() as session:
        result = await session.execute(
            text(
                """
                SELECT id, input_type, input_value, status,
                       created_at, start_time, end_time,
                       execution_time, error_message, output_path
                FROM tasks
                WHERE dataset_id = :id
                ORDER BY created_at
                """
            ),
            {"id": int(dataset_id)},
        )
        return [dict(r) for r in result.mappings().fetchall()]


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

async def get_metrics() -> Dict[str, Any]:
    """Return aggregated metrics for the dashboard."""
    _require_db()
    async with DatabaseConnection.get_session() as session:
        r = await session.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours')
                        AS jobs_today,
                    COUNT(*) FILTER (WHERE status = 'queued')
                        AS queue_length,
                    COUNT(*) FILTER (WHERE status = 'running')
                        AS running_jobs,
                    COUNT(*) FILTER (WHERE status = 'failed')
                        AS failed_jobs,
                    COUNT(*) FILTER (WHERE status = 'completed' AND created_at > NOW() - INTERVAL '24 hours')
                        AS completed_today,
                    AVG(execution_time) FILTER (WHERE status = 'completed')
                        AS avg_execution_time,
                    COUNT(*) FILTER (WHERE status = 'completed' AND created_at > NOW() - INTERVAL '1 hour')
                        AS completed_last_hour,
                    COUNT(*) FILTER (WHERE status IN ('completed', 'failed'))
                        AS total_finished,
                    COUNT(*) FILTER (WHERE status = 'completed')
                        AS total_completed
                FROM tasks
                """
            )
        )
        row = r.mappings().fetchone()
        if row is None:
            return {}

        total_finished = row["total_finished"] or 0
        total_completed = row["total_completed"] or 0
        success_rate = (total_completed / total_finished) if total_finished > 0 else 1.0

        return {
            "jobs_today": row["jobs_today"] or 0,
            "jobs_per_hour": row["completed_last_hour"] or 0,
            "average_runtime_seconds": round(row["avg_execution_time"] or 0, 1),
            "success_rate": round(success_rate, 4),
            "success_rate_pct": round(success_rate * 100, 1),
            "failed_jobs": row["failed_jobs"] or 0,
            "queue_length": row["queue_length"] or 0,
            "running_jobs": row["running_jobs"] or 0,
            "completed_today": row["completed_today"] or 0,
        }


# ---------------------------------------------------------------------------
# Protein / result helpers  (same public API as the old MongoDB version)
# ---------------------------------------------------------------------------

async def upsert_protein(doc: Dict[str, Any]) -> None:
    """Insert or update a protein cache row keyed by accession."""
    _require_db()
    accession = doc.get("accession")
    if not accession:
        raise ValueError("protein doc requires 'accession'")

    import json

    async with DatabaseConnection.get_session() as session:
        await session.execute(
            text(
                """
                INSERT INTO proteins (accession, data)
                VALUES (:accession, :data::jsonb)
                ON CONFLICT (accession) DO UPDATE
                    SET data = EXCLUDED.data
                """
            ),
            {"accession": accession, "data": json.dumps(doc)},
        )
        await session.commit()


async def get_protein(accession: str) -> Optional[Dict[str, Any]]:
    """Return cached protein data for *accession*, or None."""
    _require_db()
    async with DatabaseConnection.get_session() as session:
        result = await session.execute(
            text("SELECT data FROM proteins WHERE accession = :accession"),
            {"accession": accession},
        )
        row = result.fetchone()
        return row[0] if row else None


async def upsert_aggregate(accession: str, aggregate: Dict[str, Any]) -> None:
    _require_db()
    import json

    async with DatabaseConnection.get_session() as session:
        await session.execute(
            text(
                """
                INSERT INTO aggregates (accession, data)
                VALUES (:accession, :data::jsonb)
                ON CONFLICT (accession) DO UPDATE
                    SET data = EXCLUDED.data
                """
            ),
            {"accession": accession, "data": json.dumps(aggregate)},
        )
        await session.commit()


async def upsert_processed(accession: str, processed: Dict[str, Any]) -> None:
    _require_db()
    import json

    async with DatabaseConnection.get_session() as session:
        await session.execute(
            text(
                """
                INSERT INTO processed (accession, processed)
                VALUES (:accession, :processed::jsonb)
                ON CONFLICT (accession) DO UPDATE
                    SET processed = EXCLUDED.processed
                """
            ),
            {"accession": accession, "processed": json.dumps(processed)},
        )
        await session.commit()


async def upsert_protein_result(accession: str, output_doc: Dict[str, Any]) -> None:
    """Insert or update the final aggregated results for a completed job."""
    _require_db()
    import json

    def _j(val: Any) -> Optional[str]:
        return json.dumps(val) if val is not None else None

    async with DatabaseConnection.get_session() as session:
        await session.execute(
            text(
                """
                INSERT INTO protein_results
                    (accession, task_id, status, timestamp, output_path,
                     uniprot, pdb_files, metrics, synthesis,
                     psp_results, models_used, psp_errors, analysis, pockets)
                VALUES
                    (:accession, :task_id, :status, :timestamp, :output_path,
                     :uniprot::jsonb, :pdb_files::jsonb, :metrics::jsonb, :synthesis::jsonb,
                     :psp_results::jsonb, :models_used::jsonb, :psp_errors::jsonb,
                     :analysis::jsonb, :pockets::jsonb)
                ON CONFLICT (accession) DO UPDATE SET
                    task_id     = EXCLUDED.task_id,
                    status      = EXCLUDED.status,
                    timestamp   = EXCLUDED.timestamp,
                    output_path = EXCLUDED.output_path,
                    uniprot     = EXCLUDED.uniprot,
                    pdb_files   = EXCLUDED.pdb_files,
                    metrics     = EXCLUDED.metrics,
                    synthesis   = EXCLUDED.synthesis,
                    psp_results = EXCLUDED.psp_results,
                    models_used = EXCLUDED.models_used,
                    psp_errors  = EXCLUDED.psp_errors,
                    analysis    = EXCLUDED.analysis,
                    pockets     = EXCLUDED.pockets
                """
            ),
            {
                "accession": accession,
                "task_id": output_doc.get("task_id"),
                "status": output_doc.get("status", "completed"),
                "timestamp": output_doc.get("timestamp", datetime.now(timezone.utc)),
                "output_path": output_doc.get("output_path"),
                "uniprot": _j(output_doc.get("uniprot")),
                "pdb_files": _j(output_doc.get("pdb_files")),
                "metrics": _j(output_doc.get("metrics")),
                "synthesis": _j(output_doc.get("synthesis")),
                "psp_results": _j(output_doc.get("psp_results")),
                "models_used": _j(output_doc.get("models_used")),
                "psp_errors": _j(output_doc.get("psp_errors")),
                "analysis": _j(output_doc.get("analysis")),
                "pockets": _j(output_doc.get("pockets")),
            },
        )
        await session.commit()


async def get_protein_result(accession: str) -> Optional[Dict[str, Any]]:
    """Return the completed result record for *accession*, or None."""
    _require_db()
    async with DatabaseConnection.get_session() as session:
        result = await session.execute(
            text(
                """
                SELECT accession, task_id, status, output_path,
                       uniprot, pdb_files, metrics, synthesis,
                       psp_results, models_used, psp_errors, analysis, pockets,
                       timestamp
                FROM protein_results
                WHERE accession = :accession
                """
            ),
            {"accession": accession},
        )
        row = result.mappings().fetchone()
        if row is None:
            return None
        return dict(row)


async def get_result_by_task_id(task_id: Any) -> Optional[Dict[str, Any]]:
    """Return the completed result record for a task_id, or None."""
    _require_db()
    async with DatabaseConnection.get_session() as session:
        result = await session.execute(
            text(
                """
                SELECT accession, task_id, status, output_path,
                       uniprot, pdb_files, metrics, synthesis,
                       psp_results, models_used, psp_errors, analysis, pockets,
                       timestamp
                FROM protein_results
                WHERE task_id = :task_id
                """
            ),
            {"task_id": int(task_id)},
        )
        row = result.mappings().fetchone()
        if row is None:
            return None
        return dict(row)
