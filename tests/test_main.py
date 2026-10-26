"""
Tests for the CodeTrace FastAPI application – Phase 1.

Covers:
  - GET /            root endpoint
  - GET /api/health  health endpoint (added in Phase 1)
"""

import logging

from fastapi.testclient import TestClient
from backend.app.main import HealthCheckAccessLogFilter, app

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


def test_successful_health_check_access_log_is_filtered():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:63267", "GET", "/api/health", "1.1", 200),
        None,
    )

    assert not HealthCheckAccessLogFilter().filter(record)


def test_other_api_access_logs_remain_enabled():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:63267", "POST", "/api/notebooks/upload", "1.1", 200),
        None,
    )

    assert HealthCheckAccessLogFilter().filter(record)


def test_failed_health_check_access_log_remains_enabled():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:63267", "GET", "/api/health", "1.1", 503),
        None,
    )

    assert HealthCheckAccessLogFilter().filter(record)
