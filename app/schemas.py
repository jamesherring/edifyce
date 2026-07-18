from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class CompileRequest(BaseModel):
    code: str = Field(..., min_length=1)


class CompileResponse(BaseModel):
    success: bool
    errors: list[str] = Field(default_factory=list)
    system_name: str | None = None
    line_type_count: int | None = None
    inference_rule_count: int | None = None


class VerifyProofRequest(BaseModel):
    system_code: str = Field(..., min_length=1)
    proof_text: str


class VerifyProofResponse(BaseModel):
    success: bool
    errors: list[str] = Field(default_factory=list)
    proof: dict | None = None


class OAuthProvidersResponse(BaseModel):
    # The social-login providers that are configured, so the UI shows only the
    # buttons that will actually work. Values match the /auth/<provider> prefix.
    providers: list[str] = Field(default_factory=list)
