import uuid
from datetime import datetime

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


# ---------------------------------------------------------------------------
# Formal-system objects (CRUD)
#
# These mirror the normalised rows in app/db/systems.py and the declarative
# SystemSpec records. The read models carry each part's `id` so a client can
# address it; write models at this stage set system-level fields only (child
# CRUD is a later phase).
# ---------------------------------------------------------------------------


class Binding(BaseModel):
    """A typed variable slot, e.g. ``s : term``."""

    var: str
    sort: str


class BracketPair(BaseModel):
    id: uuid.UUID
    opening: str
    closing: str


class Sort(BaseModel):
    id: uuid.UUID
    name: str


class Production(BaseModel):
    id: uuid.UUID
    name: str
    sort: str
    kind: str
    template: str | None = None
    regex: str | None = None
    bindings: list[Binding] = Field(default_factory=list)


class LinePart(BaseModel):
    id: uuid.UUID
    name: str
    regex: str


class LineType(BaseModel):
    id: uuid.UUID
    name: str
    shape: str
    logical_sort: str | None = None
    parts: list[LinePart] = Field(default_factory=list)


class Definition(BaseModel):
    id: uuid.UUID
    sort: str
    name: str
    higher: str
    lower: str
    condition: str | None = None
    bindings: list[Binding] = Field(default_factory=list)


class Axiom(BaseModel):
    id: uuid.UUID
    label: str
    name: str
    formula: str
    bindings: list[Binding] = Field(default_factory=list)


class Rule(BaseModel):
    id: uuid.UUID
    label: str
    name: str
    deduction: str
    antecedents: list[str] = Field(default_factory=list)
    bindings: list[Binding] = Field(default_factory=list)


class FormalSystemSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    inherits_from_id: uuid.UUID | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class FormalSystemDetail(FormalSystemSummary):
    brackets: list[BracketPair] = Field(default_factory=list)
    sorts: list[Sort] = Field(default_factory=list)
    productions: list[Production] = Field(default_factory=list)
    lines: list[LineType] = Field(default_factory=list)
    definitions: list[Definition] = Field(default_factory=list)
    axioms: list[Axiom] = Field(default_factory=list)
    rules: list[Rule] = Field(default_factory=list)


class FormalSystemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str | None = None
    inherits_from_id: uuid.UUID | None = None


class FormalSystemUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    description: str | None = None
    inherits_from_id: uuid.UUID | None = None
    # True sets published_at to now, False clears it. Absent leaves it unchanged.
    published: bool | None = None


class SystemValidation(BaseModel):
    """Result of assembling the stored rows and compiling them."""

    success: bool
    errors: list[str] = Field(default_factory=list)
    system_name: str | None = None
    line_type_count: int | None = None
    inference_rule_count: int | None = None


class SystemSource(BaseModel):
    """The lowered `.edi` for the stored system (read-only transparency/export)."""

    source: str


# ---------------------------------------------------------------------------
# Child-object writes (create / update). Nested value lists (bindings,
# antecedents, line parts) are replaced wholesale on the parent write rather
# than addressed individually. On an update, an omitted field is left unchanged;
# a nested list is left unchanged when omitted and replaced when present.
# ---------------------------------------------------------------------------


class BracketCreate(BaseModel):
    opening: str = Field(..., min_length=1, max_length=16)
    closing: str = Field(..., min_length=1, max_length=16)


class BracketUpdate(BaseModel):
    opening: str | None = Field(None, min_length=1, max_length=16)
    closing: str | None = Field(None, min_length=1, max_length=16)


class SortCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


class SortUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)


class ProductionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    # The name of an existing sort in this system that the production belongs to.
    sort: str = Field(..., min_length=1)
    # Exactly one of template / regex (a composite production vs a leaf).
    template: str | None = None
    regex: str | None = None
    bindings: list[Binding] = Field(default_factory=list)


class ProductionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    sort: str | None = None
    template: str | None = None
    regex: str | None = None
    bindings: list[Binding] | None = None


class LinePartInput(BaseModel):
    name: str
    regex: str


class LineTypeCreate(BaseModel):
    name: str
    shape: str
    logical_sort: str | None = None
    parts: list[LinePartInput] = Field(default_factory=list)


class LineTypeUpdate(BaseModel):
    name: str | None = None
    shape: str | None = None
    logical_sort: str | None = None
    parts: list[LinePartInput] | None = None


class DefinitionCreate(BaseModel):
    sort: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=128)
    higher: str
    lower: str
    condition: str | None = None
    bindings: list[Binding] = Field(default_factory=list)


class DefinitionUpdate(BaseModel):
    sort: str | None = None
    name: str | None = Field(None, min_length=1, max_length=128)
    higher: str | None = None
    lower: str | None = None
    condition: str | None = None
    bindings: list[Binding] | None = None


class AxiomCreate(BaseModel):
    label: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=128)
    formula: str
    bindings: list[Binding] = Field(default_factory=list)


class AxiomUpdate(BaseModel):
    label: str | None = None
    name: str | None = Field(None, min_length=1, max_length=128)
    formula: str | None = None
    bindings: list[Binding] | None = None


class RuleCreate(BaseModel):
    label: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=128)
    deduction: str
    antecedents: list[str] = Field(default_factory=list)
    bindings: list[Binding] = Field(default_factory=list)


class RuleUpdate(BaseModel):
    label: str | None = None
    name: str | None = Field(None, min_length=1, max_length=128)
    deduction: str | None = None
    antecedents: list[str] | None = None
    bindings: list[Binding] | None = None


class ReorderRequest(BaseModel):
    """A full permutation of a collection's ids, in the desired order."""

    ids: list[uuid.UUID] = Field(..., min_length=1)
