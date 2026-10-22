"""
Tests for the CodeTrace FastAPI application – Phase 1.

Covers:
  - GET /            root endpoint
  - GET /api/health  health endpoint (added in Phase 1)
"""

from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


# ── Root endpoint ────────────────────────────────────────────────────────────

def test_root_returns_200():
    """GET / should return 200."""
    response = client.get("/")
    assert response.status_code == 200


def test_root_has_status_ok():
    """GET / body must contain status == 'ok'."""
    data = client.get("/").json()
    assert data["status"] == "ok"


def test_root_has_message():
    """GET / body must contain a non-empty message field."""
    data = client.get("/").json()
    assert "message" in data and data["message"]


# ── /api/health endpoint ─────────────────────────────────────────────────────

def test_api_health_returns_200():
    """GET /api/health should return HTTP 200."""
    response = client.get("/api/health")
    assert response.status_code == 200


def test_api_health_status_is_healthy():
    """GET /api/health body must report status == 'healthy'."""
    data = client.get("/api/health").json()
    assert data["status"] == "healthy"


def test_api_health_service_name():
    """GET /api/health body must include the service name."""
    data = client.get("/api/health").json()
    assert data["service"] == "CodeTrace API"
