import pytest

pytest.importorskip("pydantic")

from pydantic import ValidationError

from app.schemas import (
    HealthResponse,
    ProofVerifyRequest,
    VerifyProofResponse,
)


# ---------------------------------------------------------------------------
# HealthResponse
# ---------------------------------------------------------------------------


def test_health_response_defaults_to_ok():
    assert HealthResponse().status == "ok"


# ---------------------------------------------------------------------------
# ProofVerifyRequest — the DB-backed verify body (proof text only)
# ---------------------------------------------------------------------------


def test_proof_verify_request_accepts_empty_proof_text():
    assert ProofVerifyRequest(proof_text="").proof_text == ""


def test_proof_verify_request_requires_proof_text():
    with pytest.raises(ValidationError):
        ProofVerifyRequest()


# ---------------------------------------------------------------------------
# VerifyProofResponse
# ---------------------------------------------------------------------------


def test_verify_response_defaults():
    response = VerifyProofResponse(success=True)
    assert response.errors == []
    assert response.proof is None


def test_verify_response_holds_proof_data():
    proof = {"indicator": "ok", "lines": []}
    assert VerifyProofResponse(success=True, proof=proof).proof == proof
