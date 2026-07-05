import pytest

pytest.importorskip("pydantic")

from pydantic import ValidationError

from app.schemas import (
    CompileRequest,
    CompileResponse,
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
# CompileRequest
# ---------------------------------------------------------------------------


def test_compile_request_accepts_code():
    assert CompileRequest(code="FormalSystem X:").code == "FormalSystem X:"


def test_compile_request_rejects_empty_code():
    with pytest.raises(ValidationError):
        CompileRequest(code="")


def test_compile_request_requires_code():
    with pytest.raises(ValidationError):
        CompileRequest()


# ---------------------------------------------------------------------------
# CompileResponse
# ---------------------------------------------------------------------------


def test_compile_response_defaults():
    response = CompileResponse(success=True)
    assert response.errors == []
    assert response.system_name is None
    assert response.line_type_count is None
    assert response.inference_rule_count is None


def test_compile_response_error_lists_are_independent():
    first = CompileResponse(success=False)
    first.errors.append("boom")
    assert CompileResponse(success=False).errors == []


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
