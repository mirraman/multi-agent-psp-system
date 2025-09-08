from time import sleep
from typing import Any, Dict

from app.celery_app import celery_app
from app.agents.data_agent import DataAgent
from app.agents.processing_agent import ProcessingAgent


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
    return agent.run(data)



