from time import sleep
from typing import Any, Dict

from app.celery_app import celery_app
from app.agents.data_agent import DataAgent
from app.agents.processing_agent import ProcessingAgent
from app.agents.output_agent import OutputAgent
from app.utils.db import MongoConnection, upsert_protein_result


@celery_app.task(name="app.tasks.ping")
def ping(message: str) -> str:
    sleep(1)
    return f"pong: {message}"


@celery_app.task(name="app.tasks.data_agent_task")
def data_agent_task(accession: str) -> Dict[str, Any]:
    agent = DataAgent()
    return agent.run(accession)


@celery_app.task(name="app.tasks.processing_agent_task")
def processing_agent_task(data: Dict[str, Any]) -> Dict[str, Any]:
    agent = ProcessingAgent()
    processed = agent.run(data)
    return {
        "accession": data.get("accession"),
        "raw": data,
        "processed": processed,
    }



@celery_app.task(name="app.tasks.output_agent_task")
def output_agent_task(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Expects a payload with keys: accession, raw, processed
    """
    accession = args.get("accession")
    raw = args.get("raw") or {}
    processed = args.get("processed") or {}

    agent = OutputAgent()
    output = agent.run(accession, raw, processed)

    # Best-effort async save using Motor via a synchronous wrapper
    # Celery tasks here are sync; we cannot await. We will perform
    # a fire-and-forget by spinning the event loop in a minimal way
    # only if MONGODB_URI is set and connection is available.
    import os
    mongo_uri = os.getenv("MONGODB_URI")
    if mongo_uri:
        try:
            import asyncio

            async def _save() -> None:
                if MongoConnection.db is None:
                    await MongoConnection.init(mongo_uri)
                await upsert_protein_result(accession, output)

            asyncio.run(_save())
        except Exception:
            pass

    return output

