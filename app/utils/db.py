from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# Schema DDL – created on first startup via _create_tables()
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    id          SERIAL PRIMARY KEY,
    type        TEXT NOT NULL DEFAULT 'protein_structure_pipeline',
    input_type  TEXT NOT NULL DEFAULT 'accession',
    input_value TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    output_path TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status     ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);

CREATE TABLE IF NOT EXISTS proteins (
    id        SERIAL PRIMARY KEY,
    accession TEXT UNIQUE NOT NULL,
    data      JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS protein_results (
    id          SERIAL PRIMARY KEY,
    accession   TEXT UNIQUE NOT NULL,
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
# Helper functions  (same public API as the old MongoDB version)
# ---------------------------------------------------------------------------

def _require_db() -> None:
    if DatabaseConnection.engine is None:
        raise RuntimeError("Database not initialized")


async def insert_task(task: Dict[str, Any]) -> str:
    """Insert a new task row and return its id as a string."""
    _require_db()
    async with DatabaseConnection.get_session() as session:
        result = await session.execute(
            text(
                """
                INSERT INTO tasks (type, input_type, input_value, status, created_at)
                VALUES (:type, :input_type, :input_value, :status, :created_at)
                RETURNING id
                """
            ),
            {
                "type": task.get("type", "protein_structure_pipeline"),
                "input_type": task.get("input_type", "accession"),
                "input_value": task["input_value"],
                "status": task.get("status", "pending"),
                "created_at": task.get("created_at", datetime.now(timezone.utc)),
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


async def claim_pending_job() -> Optional[Dict[str, Any]]:
    """
    Atomically claim the oldest pending task (SELECT … FOR UPDATE SKIP LOCKED).
    Returns the row as a dict, or None if the queue is empty.
    """
    _require_db()
    async with DatabaseConnection.get_session() as session:
        result = await session.execute(
            text(
                """
                SELECT id, type, input_type, input_value, status, created_at, output_path
                FROM tasks
                WHERE status = 'pending'
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """
            )
        )
        row = result.mappings().fetchone()
        if row is None:
            return None

        await session.execute(
            text("UPDATE tasks SET status = 'processing' WHERE id = :id"),
            {"id": row["id"]},
        )
        await session.commit()
        return dict(row)


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
                    (accession, status, timestamp, output_path,
                     uniprot, pdb_files, metrics, synthesis,
                     psp_results, models_used, psp_errors, analysis, pockets)
                VALUES
                    (:accession, :status, :timestamp, :output_path,
                     :uniprot::jsonb, :pdb_files::jsonb, :metrics::jsonb, :synthesis::jsonb,
                     :psp_results::jsonb, :models_used::jsonb, :psp_errors::jsonb,
                     :analysis::jsonb, :pockets::jsonb)
                ON CONFLICT (accession) DO UPDATE SET
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
                SELECT accession, status, output_path,
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
