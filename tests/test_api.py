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


def test_verify_returns_structured_error_when_checker_raises(monkeypatch):
    # A system can compile successfully but still raise while checking a
    # proof (e.g. a context edit targeting a missing proof-context key).
    # The API must return a structured verification error, not a 500.
    import app.main as main

    class ExplodingSystem:
        def parse(self, text):
            raise Exception("Can't find 'bad' in proof context.")

    monkeypatch.setattr(
        main, "compile_formal_system", lambda code: {"system": ExplodingSystem()}
    )

    response = client.post(
        "/proofs/verify",
        json={"system_code": "system code", "proof_text": "proof"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "errors": ["Can't find 'bad' in proof context."],
        "proof": None,
    }
