import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("regex")

from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


def test_healthcheck():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_compile_requires_code():
    response = client.post("/formal-systems/compile", json={"code": ""})
    assert response.status_code == 422


def test_verify_rejects_invalid_system_code():
    response = client.post(
        "/proofs/verify",
        json={"system_code": "", "proof_text": ""},
    )
    assert response.status_code == 422
