import pytest

pytest.importorskip("pydantic")

from pydantic import ValidationError

from app.schemas import (
    HealthResponse,
    VerifyProofRequest,
    VerifyProofResponse,
)


# ---------------------------------------------------------------------------
# HealthResponse
# ---------------------------------------------------------------------------


def test_health_response_defaults_to_ok():
    assert HealthResponse().status == "ok"


# ---------------------------------------------------------------------------
# VerifyProofRequest
# ---------------------------------------------------------------------------


def test_verify_request_accepts_empty_proof_text():
    request = VerifyProofRequest(system_code="FormalSystem X:", proof_text="")
    assert request.proof_text == ""


def test_verify_request_rejects_empty_system_code():
    with pytest.raises(ValidationError):
        VerifyProofRequest(system_code="", proof_text="abc")


def test_verify_request_requires_proof_text():
    with pytest.raises(ValidationError):
        VerifyProofRequest(system_code="FormalSystem X:")


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
