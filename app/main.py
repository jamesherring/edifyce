from fastapi import FastAPI, HTTPException

from app.schemas import (
    CompileRequest,
    CompileResponse,
    HealthResponse,
    VerifyProofRequest,
    VerifyProofResponse,
)
from website.logical.compiler import compile as compile_formal_system

app = FastAPI(
    title="Edifyce API",
    version="2.0.0",
    description="FastAPI backend for compiling formal systems and verifying proofs.",
)


@app.get("/health", response_model=HealthResponse)
def healthcheck() -> HealthResponse:
    return HealthResponse()


@app.post("/formal-systems/compile", response_model=CompileResponse)
def compile_system(payload: CompileRequest) -> CompileResponse:
    result = compile_formal_system(payload.code)

    if "errors" in result:
        return CompileResponse(success=False, errors=result["errors"])

    system = result["system"]
    system_name = system.name if system.name else None

    return CompileResponse(
        success=True,
        system_name=system_name,
        line_type_count=len(system.line_types),
        inference_rule_count=len(system.inference_rules),
    )


@app.post("/proofs/verify", response_model=VerifyProofResponse)
def verify_proof(payload: VerifyProofRequest) -> VerifyProofResponse:
    compile_result = compile_formal_system(payload.system_code)

    if "errors" in compile_result:
        raise HTTPException(status_code=400, detail=compile_result["errors"])

    system = compile_result["system"]
    proof = system.parse(payload.proof_text)

    return VerifyProofResponse(success=proof.valid, proof=proof.data())
