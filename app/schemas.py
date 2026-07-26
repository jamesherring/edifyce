import uuid
from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """One page of a server-paginated list.

    ``items`` is the current slice; ``total`` is the full count matching the
    query (before ``limit``/``offset``), so a client can render page controls
    without a second request. ``limit``/``offset`` echo the request back.
    """

    items: list[T]
    total: int
    limit: int
    offset: int


# How a rule justifies a step: "structural" (first-order term unification, the
# default) or "string" (associative matching for a string-rewriting system such
# as MIU). Mirrors RuleRow.matching / InferenceRule.matching.
RuleMatching = Literal["structural", "string"]

# The subproof scope a line type opens: "assumption" (a hypothesis) or
# "variable" (a fresh variable); None opens no scope. Mirrors LineRow.scope /
# LineType.scope / declarative LineSpec.scope.
LineScope = Literal["assumption", "variable"]
# What the checker does with a line type. Mirrors declarative._LINE_BEHAVIOURS,
# which is the authority on why `axiom` is not authorable here.
LineBehaviour = Literal["logical", "comment"]

# Free-text fields map to length-bounded DB columns (see app/db/systems.py). The
# caps below mirror those `String(N)` widths so oversized input is rejected as a
# 422 rather than reaching the INSERT and erroring on Postgres.
_Text512 = Annotated[str, Field(max_length=512)]


class HealthResponse(BaseModel):
    status: str = "ok"


class VerifyProofResponse(BaseModel):
    success: bool
    errors: list[str] = Field(default_factory=list)
    proof: dict | None = None


class ProofVerifyRequest(BaseModel):
    """Verify a proof against a *stored* system (identified by URL), so the
    system source never crosses the wire — the server assembles it from rows."""

    proof_text: str


class OAuthProvidersResponse(BaseModel):
    # The social-login providers that are configured, so the UI shows only the
    # buttons that will actually work. Values match the /auth/<provider> prefix.
    providers: list[str] = Field(default_factory=list)


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

    var: str = Field(..., max_length=64)
    sort: str = Field(..., max_length=128)


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
    atom_value: str | None = None
    atom_base: str | None = None
    # Whether this production's tokens are *constants* of the object language
    # rather than variables of it — Metamath's `$c` vs `$v`. Declared, never
    # inferred: `⊥` in `formula ::= ⊥` and `a` in `setvar ::= a | b | c` are the
    # same shape and opposite answers. Only a constant may appear in a
    # definition's defining form without the defined form supplying it.
    denotes_constant: bool = False
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
    # The subproof scope this line opens: None, "assumption" or "variable".
    scope: str | None = None
    # "logical" (asserts a formula, must be justified) or "comment" (prose).
    behaviour: str = "logical"
    parts: list[LinePart] = Field(default_factory=list)


class Definition(BaseModel):
    id: uuid.UUID
    sort: str
    name: str
    higher: str
    lower: str
    # Soundness provisos, one kernel-vocabulary line each (implicit conjunction) —
    # the same structured surface a rule exposes via `side_conditions`.
    provisos: list[str] = Field(default_factory=list)
    # Deprecated compatibility view: the provisos joined with `;` as a single
    # `where` string. Derived from the same tree as `provisos`; prefer `provisos`.
    condition: str | None = None
    bindings: list[Binding] = Field(default_factory=list)
    # The defining form's bound variables (the `fresh` clause). Declaring them lets
    # a quantified definition take the kernel path, so a proviso on it is enforced.
    fresh: list[Binding] = Field(default_factory=list)
    # Optional name a proof cites this definition by (`[<label>, <line>]`); null
    # when unnamed. Unique within a system.
    label: str | None = None


class Axiom(BaseModel):
    id: uuid.UUID
    label: str
    name: str
    formula: str
    bindings: list[Binding] = Field(default_factory=list)


class Subproof(BaseModel):
    """The subproof a discharge rule consumes (→I, RAA, ∀I).

    ``derive`` is the pattern the subproof's final line must match; it is opened
    by exactly one of ``assume`` (a hypothesis) or ``fresh`` (an eigenvariable).
    Mirrors declarative ``Subproof`` / engine ``SubproofSchema``.
    """

    derive: _Text512
    assume: _Text512 | None = None
    fresh: _Text512 | None = None

    @model_validator(mode="after")
    def _exactly_one_opener(self) -> "Subproof":
        if (self.assume is None) == (self.fresh is None):
            raise ValueError("A subproof must be opened by exactly one of 'assume' or 'fresh'.")
        return self


class Rule(BaseModel):
    id: uuid.UUID
    label: str
    name: str
    deduction: str
    antecedents: list[str] = Field(default_factory=list)
    bindings: list[Binding] = Field(default_factory=list)
    # Soundness provisos, one kernel-vocabulary line each (implicit conjunction).
    side_conditions: list[str] = Field(default_factory=list)
    matching: RuleMatching = "structural"
    # The subproof a discharge rule consumes, or None for a line-antecedent rule.
    subproof: Subproof | None = None
    # Whether a citation may name more lines than the rule has antecedent slots;
    # the surplus is kept unconstrained. Off by default (an exact citation).
    allow_extra_antecedents: bool = False


class SystemOwner(BaseModel):
    """The public face of a system's owner. Deliberately omits email — only the
    id and a chosen display name are surfaced on shared (published) systems."""

    id: uuid.UUID
    display_name: str | None = None


class FormalSystemSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    inherits_from_id: uuid.UUID | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # Null for ownerless systems (owner_id is nullable).
    owner: SystemOwner | None = None


class FormalSystemDetail(FormalSystemSummary):
    brackets: list[BracketPair] = Field(default_factory=list)
    # See declarative.SystemSpec.token_separated.
    token_separated: bool = False
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
    sort: str = Field(..., min_length=1, max_length=128)
    # Exactly one of template / regex / atom_value / atom_base — a composite
    # (notation), a leaf regex, an atom constant, or an atom family respectively.
    # The atom fields are min_length=1: an empty base would match `_0`, `_1`, …
    # and an empty constant no token at all, so neither may be stored.
    template: str | None = Field(None, max_length=512)
    regex: str | None = Field(None, max_length=512)
    atom_value: str | None = Field(None, min_length=1, max_length=512)
    atom_base: str | None = Field(None, min_length=1, max_length=128)
    # See `Production.denotes_constant`. Defaults off: leaving it out treats the
    # production as variable-like, which costs a refused definition rather than a
    # capturing one.
    denotes_constant: bool = False
    bindings: list[Binding] = Field(default_factory=list)


class ProductionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    sort: str | None = Field(None, max_length=128)
    template: str | None = Field(None, max_length=512)
    regex: str | None = Field(None, max_length=512)
    atom_value: str | None = Field(None, min_length=1, max_length=512)
    atom_base: str | None = Field(None, min_length=1, max_length=128)
    denotes_constant: bool | None = None
    bindings: list[Binding] | None = None


class LinePartInput(BaseModel):
    name: str = Field(..., max_length=128)
    regex: str = Field(..., max_length=512)


class LineTypeCreate(BaseModel):
    name: str = Field(..., max_length=128)
    shape: str = Field(..., max_length=256)
    logical_sort: str | None = Field(None, max_length=128)
    # The subproof scope the line opens; the engine accepts only these two
    # openers (or none), so an invalid value is a 422 rather than a build error.
    scope: LineScope | None = None
    behaviour: LineBehaviour = "logical"
    parts: list[LinePartInput] = Field(default_factory=list)


class LineTypeUpdate(BaseModel):
    name: str | None = Field(None, max_length=128)
    shape: str | None = Field(None, max_length=256)
    logical_sort: str | None = Field(None, max_length=128)
    scope: LineScope | None = None
    behaviour: LineBehaviour | None = None
    parts: list[LinePartInput] | None = None


class DefinitionCreate(BaseModel):
    sort: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=128)
    higher: _Text512
    lower: _Text512
    # Structured provisos (preferred), mirroring rules' `side_conditions`.
    provisos: list[_Text512] = Field(default_factory=list)
    # Deprecated compatibility input: a single `;`-joined `where` string. Ignored
    # when `provisos` is supplied; kept so pre-D0 clients keep working.
    condition: str | None = Field(None, max_length=512)
    bindings: list[Binding] = Field(default_factory=list)
    # The defining form's bound variables (the `fresh` clause).
    fresh: list[Binding] = Field(default_factory=list)
    # Optional citation name (`[<label>, <line>]`); must be unique within a system.
    label: str | None = Field(None, max_length=64)


class DefinitionUpdate(BaseModel):
    sort: str | None = Field(None, max_length=128)
    name: str | None = Field(None, min_length=1, max_length=128)
    higher: str | None = Field(None, max_length=512)
    lower: str | None = Field(None, max_length=512)
    # Provisos (preferred); wins over `condition` when both are present.
    provisos: list[_Text512] | None = None
    # Deprecated compatibility input; see DefinitionCreate.
    condition: str | None = Field(None, max_length=512)
    bindings: list[Binding] | None = None
    fresh: list[Binding] | None = None
    label: str | None = Field(None, max_length=64)


class AxiomCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    formula: _Text512
    bindings: list[Binding] = Field(default_factory=list)


class AxiomUpdate(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=64)
    name: str | None = Field(None, min_length=1, max_length=128)
    formula: str | None = Field(None, max_length=512)
    bindings: list[Binding] | None = None


class RuleCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    deduction: _Text512
    antecedents: list[_Text512] = Field(default_factory=list)
    bindings: list[Binding] = Field(default_factory=list)
    side_conditions: list[_Text512] = Field(default_factory=list)
    matching: RuleMatching = "structural"
    subproof: Subproof | None = None
    allow_extra_antecedents: bool = False


class RuleUpdate(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=64)
    name: str | None = Field(None, min_length=1, max_length=128)
    deduction: str | None = Field(None, max_length=512)
    antecedents: list[_Text512] | None = None
    bindings: list[Binding] | None = None
    side_conditions: list[_Text512] | None = None
    matching: RuleMatching | None = None
    subproof: Subproof | None = None
    allow_extra_antecedents: bool | None = None


class ReorderRequest(BaseModel):
    """A full permutation of a collection's ids, in the desired order."""

    ids: list[uuid.UUID] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Proofs (CRUD)
#
# Mirror the formal-system CRUD models: a proof is an owner-scoped object that
# belongs to a formal system, carries its proof text (lines written in that
# system's own grammar), and is verified against it on demand. Like systems,
# publishing makes it
# world-readable. The read models carry the cached `valid`/`result` snapshot so
# a client can render the last check without re-running it. `folder_id` is
# surfaced read-only — folder CRUD (like formal-system child parts) is a later
# phase.
# ---------------------------------------------------------------------------


# A citation alias must be a safe label for `[alias.line]` — no `.`/`,`/brackets/
# spaces, which the proof-line citation grammar uses as delimiters.
_ALIAS_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]*$"


class ProofReferenceInput(BaseModel):
    """One outgoing reference edge, as submitted: the lemma proof plus the alias
    this proof cites it by in its source (`[alias.line]`)."""

    referenced_proof_id: uuid.UUID
    alias: str = Field(..., min_length=1, max_length=64, pattern=_ALIAS_PATTERN)


class ProofReferenceOut(BaseModel):
    """One outgoing reference edge, read back: the alias plus the referenced
    proof's public identity."""

    referenced_proof_id: uuid.UUID
    alias: str
    name: str
    slug: str
    published: bool


class ProofReferrerOut(BaseModel):
    """One incoming reference edge, read back: a proof that cites this one as a
    lemma (the "used by" direction), with the alias it cites this proof under.

    Carries no ``slug``: the "used by" list routes by ``proof_id`` and shows the
    referrer's name, so a slug would be dead payload."""

    proof_id: uuid.UUID
    alias: str
    name: str
    published: bool


class ProofReferencesUpdate(BaseModel):
    """Replace a proof's full set of outgoing references (wholesale, like the
    nested value lists on system parts)."""

    references: list[ProofReferenceInput] = Field(default_factory=list)


class ProofSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    formal_system_id: uuid.UUID
    folder_id: uuid.UUID | None = None
    # Last-known validity; null until the proof has been verified.
    valid: bool | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # Null for ownerless proofs (owner_id is nullable). Reuses the system owner's
    # public face — id + display name, never email.
    owner: SystemOwner | None = None


class ProofDetail(ProofSummary):
    source: str
    # Cached `proof.data()` payload from the last verification (null = never run).
    result: dict | None = None
    # Outgoing references (lemmas this proof cites), in display order.
    references: list[ProofReferenceOut] = Field(default_factory=list)
    # Incoming references (proofs that cite this one as a lemma) — the "used by"
    # direction. Filtered to those the viewer may read.
    referenced_by: list[ProofReferrerOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stored proof structure
#
# The read side of app/db/proof_lines.py: a checked proof decomposed into rows —
# one per source line, each formula a root in the system's term graph, and the
# justification edges between them. Written by verification, dropped when the
# verdict is. Distinct from ProofDetail.result, which is the *display* snapshot
# the editor renders; this is the structure the engine actually derived.
# ---------------------------------------------------------------------------


class TermSummary(BaseModel):
    """A term-graph node's identity, without its children.

    The DAG below it is queryable in SQL (`term_children`); what a client needs
    here is the root's shape and its two search keys — ``digest`` (exact) and
    ``alpha_digest`` (up to consistent renaming of free variables), so equal
    statements can be grouped without re-parsing anything."""

    id: uuid.UUID
    kind: str
    constructor: str | None = None
    literal: str | None = None
    sort: str | None = None
    digest: str
    alpha_digest: str | None = None


class ProofLineAntecedentOut(BaseModel):
    """One justification edge: a line this line was derived from.

    Exactly one target form is populated — ``line_id`` for a citation within this
    proof, or ``proof_id``/``number`` for one reaching into a cited lemma (which
    owns its own line rows)."""

    role: str
    position: int
    line_id: uuid.UUID | None = None
    proof_id: uuid.UUID | None = None
    number: int | None = None


class ProofLineOut(BaseModel):
    id: uuid.UUID
    # Index into the source's lines (blanks and commentary included), unlike
    # `number`, which is the citation number and is null for those.
    position: int
    number: int | None = None
    indent: int
    display: str
    line_type: str | None = None
    behaviour: str | None = None
    label: str | None = None
    # The citation as written, then the rule the checker resolved it to — null
    # when nothing justified the line (a scope opener, an axiom, a definitional
    # step, or an unjustified one).
    reference: str | None = None
    rule: str | None = None
    # The definition a definitional step applied. A generic `[Def, n]` citation
    # names none — the checker searches those in scope — so this is the only
    # record of which one it was.
    definition_id: uuid.UUID | None = None
    valid: bool
    invalid_message: str | None = None
    warning_message: str | None = None
    # The scope kind this line opens, and the opener of the subproof it sits in.
    opens_scope: str | None = None
    scope_id: uuid.UUID | None = None
    # The line's formula in the term graph; null for a line that bears none.
    term: TermSummary | None = None
    antecedents: list[ProofLineAntecedentOut] = Field(default_factory=list)


class ProofStructure(BaseModel):
    """A proof's stored structure, or an empty one when none is stored.

    ``stored`` says only that: a structure is on hand. It is never "derived
    nothing" — even an empty proof stores its one blank line — but nor is it
    quite "unchecked", since a proof last checked before this store existed
    carries a verdict without a structure until its next verify. Read it as
    *materialised*, and ``ProofSummary.valid`` as *checked*."""

    proof_id: uuid.UUID
    stored: bool
    lines: list[ProofLineOut] = Field(default_factory=list)


class ProofCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    # The system this proof is written against; must be owned by the caller.
    formal_system_id: uuid.UUID
    description: str | None = None
    source: str = ""


class ProofUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    description: str | None = None
    source: str | None = None
    # True sets published_at to now, False clears it. Absent leaves it unchanged.
    published: bool | None = None
