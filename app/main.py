import argparse
import json
from typing import Any, Dict
from contextlib import asynccontextmanager

import os
import logging
from fastapi import FastAPI
from fastapi import BackgroundTasks
from starlette.requests import Request
from starlette.responses import JSONResponse
from app.utils.fetchers import fetch_uniprot, fetch_pdb, fetch_alphafold, fetch_pubmed
from backend.app.agents.DataAgent import DataAgent
from celery import chain
from app.tasks import data_agent_task, processing_agent_task, output_agent_task
from fastapi import Query


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo_uri = os.getenv("MONGODB_URI")
    if mongo_uri:
        try:
            from app.utils.db import MongoConnection

            await MongoConnection.init(mongo_uri)
        except Exception as exc:
            print(f"Mongo init skipped/failed: {exc}")
    try:
        yield
    finally:
        try:
            from app.utils.db import MongoConnection

            await MongoConnection.close()
        except Exception:
            pass


app = FastAPI(lifespan=lifespan)
logger = logging.getLogger("psp.app")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


@app.get("/health")
def health_check() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/data/{accession}")
async def run_data_agent(accession: str, include_pubmed: bool = False, save: bool = False) -> Dict[str, Any]:
    agent = DataAgent()
    result = agent.run(accession, include_pubmed=include_pubmed, pubmed_api_key=os.getenv("PUBMED_API_KEY"))

    if save and os.getenv("MONGODB_URI"):
        try:
            from app.utils.db import MongoConnection, upsert_aggregate

            if MongoConnection.db is None:
                await MongoConnection.init(os.getenv("MONGODB_URI"))
            await upsert_aggregate(accession, result)
        except Exception as exc:
            logger.warning("Aggregate save failed", exc_info=exc)

    return result


@app.get("/process/{accession}")
async def process_accession(accession: str, save: bool = Query(default=False)) -> Dict[str, Any]:
    """
    Try to process via the Celery chain (requires Redis broker and a running worker).
    If the broker/worker are unavailable or an error occurs, fall back to local
    synchronous processing in this process.

    Client note: When falling back, the request will take longer (runs in-process)
    and is not asynchronous. Ensure Redis + worker are running for async behavior.
    """
    # Prefer Celery chain when broker/worker are available. This is async and fast.
    try:
        result = chain(
            data_agent_task.s(accession),
            processing_agent_task.s(),
            output_agent_task.s(),
        )().get(timeout=120)
        if isinstance(result, dict):
            return result
    except Exception as _:
        pass

    # Fallback path: run synchronously in-process if Celery/broker are unavailable.
    # This keeps the endpoint functional, but latency may be higher and it is not async.
    agent = DataAgent()
    raw = agent.run(accession)
    from backend.app.agents.ProcessingAgent import ProcessingAgent
    from backend.app.agents.OutputAgent import OutputAgent

    proc = ProcessingAgent()
    processed = proc.run(raw)
    out = OutputAgent().run(accession, raw, processed)
    if save and os.getenv("MONGODB_URI"):
        try:
            from app.utils.db import MongoConnection, upsert_protein_result

            if MongoConnection.db is None:
                await MongoConnection.init(os.getenv("MONGODB_URI"))
            await upsert_protein_result(accession, out)
        except Exception as exc:
            logger.warning("Output save failed", exc_info=exc)
    return out


@app.post("/runs/{accession}")
async def trigger_run(accession: str, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """
    Trigger the end-to-end pipeline.
    - If Celery/Redis are available, queue an async job and return task_id.
    - If not available, fall back to a FastAPI BackgroundTask to compute and save.
    """
    # Try Celery async path first
    try:
        task = chain(
            data_agent_task.s(accession),
            processing_agent_task.s(),
            output_agent_task.s(),
        ).apply_async()
        return {"status": "queued", "accession": accession, "task_id": task.id}
    except Exception as exc:
        logger.info("Celery unavailable, falling back to FastAPI background task", exc_info=exc)

    # Fallback: run in background within this process, best-effort save if Mongo configured
    def _run_sync() -> None:
        try:
            agent = DataAgent()
            raw = agent.run(accession)
            from backend.app.agents.ProcessingAgent import ProcessingAgent
            from backend.app.agents.OutputAgent import OutputAgent

            proc = ProcessingAgent()
            processed = proc.run(raw)
            out = OutputAgent().run(accession, raw, processed)

            import os as _os
            mongo_uri = _os.getenv("MONGODB_URI")
            if mongo_uri:
                import asyncio as _asyncio
                from app.utils.db import MongoConnection, upsert_protein_result

                async def _save() -> None:
                    if MongoConnection.db is None:
                        await MongoConnection.init(mongo_uri)
                    await upsert_protein_result(accession, out)

                try:
                    _asyncio.run(_save())
                except Exception as save_exc:
                    logger.warning("Background fallback save failed", exc_info=save_exc)
        except Exception as run_exc:
            logger.exception("Background fallback run failed", exc_info=run_exc)

    background_tasks.add_task(_run_sync)
    return {"status": "queued", "accession": accession, "mode": "background"}


@app.get("/protein/{accession}")
async def get_protein(accession: str) -> Dict[str, Any]:
    try:
        from app.utils.db import MongoConnection, get_protein_result

        if MongoConnection.db is None:
            mongo_uri = os.getenv("MONGODB_URI")
            if mongo_uri:
                await MongoConnection.init(mongo_uri)
        if MongoConnection.db is None:
            return {"error": "Mongo not initialized"}
        doc = await get_protein_result(accession)
        if not doc:
            return {"error": "No results found"}
        return doc
    except Exception as exc:
        logger.exception("Failed to get protein result", exc_info=exc)
        return {"error": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Protein data fetch CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    uni = sub.add_parser("uniprot", help="Fetch UniProt entry by accession")
    uni.add_argument("accession", type=str)

    pdb = sub.add_parser("pdb", help="Fetch PDB metadata by ID")
    pdb.add_argument("pdb_id", type=str)

    af = sub.add_parser("alphafold", help="Fetch AlphaFold prediction by UniProt accession")
    af.add_argument("accession", type=str)

    pm = sub.add_parser("pubmed", help="Search PubMed for a query")
    pm.add_argument("query", type=str)
    pm.add_argument("--api-key", dest="api_key", type=str, default=os.getenv("PUBMED_API_KEY"))
    pm.add_argument("--retmax", type=int, default=5)

    agent = sub.add_parser("agent", help="Run DataAgent pipeline")
    agent.add_argument("accession", nargs="?", default="P69905")
    agent.add_argument("--include-pubmed", action="store_true")
    agent.add_argument("--api-key", dest="api_key", type=str, default=os.getenv("PUBMED_API_KEY"))
    agent.add_argument("--retmax", type=int, default=5)

    args = parser.parse_args()

    try:
        if args.cmd == "uniprot":
            result: Dict[str, Any] = fetch_uniprot(args.accession)
        elif args.cmd == "pdb":
            result = fetch_pdb(args.pdb_id)
        elif args.cmd == "alphafold":
            result = fetch_alphafold(args.accession)
        elif args.cmd == "pubmed":
            result = fetch_pubmed(args.query, api_key=args.api_key, retmax=args.retmax)
        elif args.cmd == "agent":
            agent = DataAgent()
            result = agent.run(
                args.accession,
                include_pubmed=args.include_pubmed,
                pubmed_api_key=args.api_key,
                pubmed_retmax=args.retmax,
            )
        else:
            parser.error("Unknown command")
            return
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        raise

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()


