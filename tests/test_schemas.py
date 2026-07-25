import pytest

pytest.importorskip("pydantic")

from typing import get_args

from pydantic import ValidationError

from app.schemas import (
    HealthResponse,
    LineBehaviour,
    LineScope,
    ProofVerifyRequest,
    VerifyProofResponse,
)
from website.logical.declarative import _LINE_BEHAVIOURS, _LINE_SCOPES


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


# ---------------------------------------------------------------------------
# Line vocabularies
# ---------------------------------------------------------------------------
#
# `LineBehaviour` / `LineScope` restate the engine's authorable sets as literals
# so the generated OpenAPI schema stays legible. Nothing imports one from the
# other, so these pin the two together: if the engine's vocabulary moves, the
# API's must move with it rather than silently drift.


def test_line_behaviour_matches_the_declarative_vocabulary() -> None:
    assert set(get_args(LineBehaviour)) == set(_LINE_BEHAVIOURS)


def test_line_scope_matches_the_declarative_vocabulary() -> None:
    # `_LINE_SCOPES` carries None for "opens no scope"; the API expresses that as
    # an absent/null field rather than a member of the literal.
    assert set(get_args(LineScope)) == {s for s in _LINE_SCOPES if s is not None}
