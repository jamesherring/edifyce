import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("regex")

from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_healthcheck():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# Proof verification now runs against *stored* systems, not raw source: see
# `POST /formal-systems/{id}/verify` in tests/test_systems_api.py. There is no
# raw-`.edi` compile or verify endpoint any more.
