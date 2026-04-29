from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["region"]
    # Model is configurable via BEDROCK_MODEL_ID; default is the desired
    # Claude profile, runtime may override (see settings.py for the SCP note).
    assert body["model"]
    assert body["tools"] >= 6


def test_root_lists_tools() -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "bedrock_agent"
    assert "list_databases" in body["tools"]
    assert "run_athena_query" in body["tools"]
