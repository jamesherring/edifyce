import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("regex")

from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


# A minimal but fully valid formal system: compiles cleanly and can
# parse a one-line proof.
MINIMAL_SYSTEM = """FormalSystem Minimal:

    Regex anything:
        ^[a-z ]+$

    ProofContext:
        given: MatchSet()

    LineType statement:
        pattern: anything
        behaviour: none
"""

# Compiles successfully, but its `indent` line type edits a proof-context
# key ("bad") that the ProofContext never defines, so the checker raises
# from ProofLine.edit_context when a proof reaches that line. This is the
# scenario from the PR review: parse-time exceptions must surface as a
# structured verification error, not a 500.
BAD_CONTEXT_SYSTEM = """FormalSystem BadContext:

    Regex anything:
        ^[a-zA-Z ]+$

    ProofContext:
        given: MatchSet()

    LineType statement:
        pattern: anything
        behaviour: logical

    Pattern if_pattern:
        with s as anything:
            if s:

    LineType if:
        pattern: if_pattern
        behaviour: indent
        context.bad:
            union: match().s
"""

# `123bad` is not a valid variable name, which is one of the few inputs
# that populates the compiler's error log.
INVALID_SYSTEM = """FormalSystem Broken:

    Regex 123bad:
        ^.+$
"""


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_healthcheck():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /proofs/verify — request validation
# ---------------------------------------------------------------------------


def test_verify_rejects_empty_system_code():
    response = client.post(
        "/proofs/verify",
        json={"system_code": "", "proof_text": ""},
    )
    assert response.status_code == 422


def test_verify_requires_proof_text_field():
    response = client.post("/proofs/verify", json={"system_code": MINIMAL_SYSTEM})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# /proofs/verify — behaviour
# ---------------------------------------------------------------------------


def test_verify_returns_400_when_system_does_not_compile():
    response = client.post(
        "/proofs/verify",
        json={"system_code": INVALID_SYSTEM, "proof_text": "anything"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": ["3: Invalid variable name: '123bad'."]}


def test_verify_valid_proof_returns_proof_data():
    response = client.post(
        "/proofs/verify",
        json={"system_code": MINIMAL_SYSTEM, "proof_text": "hello world"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["errors"] == []
    proof = body["proof"]
    assert proof["indicator"] == "ok"
    assert len(proof["lines"]) == 1
    line = proof["lines"][0]
    assert line["valid"] is True
    assert line["name"] == "statement"
    assert line["display"] == "hello world"


def test_verify_unparseable_line_is_reported_not_raised():
    # "HELLO 123" matches no line type in MINIMAL_SYSTEM; the checker
    # reports it as an invalid line rather than raising.
    response = client.post(
        "/proofs/verify",
        json={"system_code": MINIMAL_SYSTEM, "proof_text": "HELLO 123"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["proof"]["indicator"] == "error"
    line = body["proof"]["lines"][0]
    assert line["valid"] is False
    assert line["invalid_message"] == "Could not parse line."


def test_verify_checker_exception_returns_structured_error():
    # Regression test for the PR review finding, exercised through the
    # real engine: BAD_CONTEXT_SYSTEM compiles, but verifying a proof
    # that reaches the `if` line raises from ProofLine.edit_context.
    response = client.post(
        "/proofs/verify",
        json={"system_code": BAD_CONTEXT_SYSTEM, "proof_text": "if hello:"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "errors": ["Can't find 'bad' in proof context."],
        "proof": None,
    }


def test_verify_checker_exception_returns_structured_error_stubbed(monkeypatch):
    # Same contract, engine-independent: any exception from parse() must
    # be converted into a structured error response.
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
