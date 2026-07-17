"""Tests for the health endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_200() -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200


def test_health_payload_shape() -> None:
    resp = client.get("/api/health")
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body) >= {"status", "version", "git_sha", "time"}
    assert body["version"]
    assert body["git_sha"]
