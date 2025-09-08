from time import sleep

from app.celery_app import celery_app


@celery_app.task(name="app.tasks.ping")
def ping(message: str) -> str:
    # Simulate work
    sleep(1)
    return f"pong: {message}"


