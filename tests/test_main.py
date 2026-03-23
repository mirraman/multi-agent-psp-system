from fastapi.testclient import TestClient

from app.main import app
from app.utils.db import DatabaseConnection


def test_openapi_docs_available():
    with TestClient(app) as client:
        r = client.get("/docs")
        assert r.status_code == 200


def test_openapi_json_available():
    with TestClient(app) as client:
        r = client.get("/openapi.json")
        assert r.status_code == 200
        assert r.json().get("openapi")


def test_create_job_returns_503_when_database_unavailable(monkeypatch):
    with TestClient(app) as client:
        monkeypatch.setattr(DatabaseConnection, "engine", None)
        r = client.post(
            "/jobs",
            json={"type": "protein_analysis", "accession": "P12345"},
        )
        assert r.status_code == 503
