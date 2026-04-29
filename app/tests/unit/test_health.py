from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["region"]
    assert body["model"].startswith("eu.anthropic.claude-")


def test_root_advertises_phase() -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["service"] == "bedrock_agent"
