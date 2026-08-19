import uuid
from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

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

# What an edge between two systems claims, and whether it has earned it.
# Mirrors app/db/system_relations.py's RELATION_KINDS / RELATION_STATUSES, which
# are the authority on what each means.
RelationKind = Literal["extension", "interpretation"]
RelationStatus = Literal["draft", "discharged"]

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
# A grammar name or a label, as `String(128)` columns hold them.
_Name128 = Annotated[str, Field(min_length=1, max_length=128)]
_Text64 = Annotated[str, Field(min_length=1, max_length=64)]


class HealthResponse(BaseModel):
    status: str = "ok"


class SlotReportOut(BaseModel):
    """One antecedent slot of a rule, and how the citation fared against it."""

    index: int
    schema_: str = Field(alias="schema")
    candidates: list[int] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class FailureOut(BaseModel):
    """Why a line is not established, as data beside the sentence.

    Mirrors `website.logical.formal_system.diagnostics.Failure`. Every field past
    `code` and `message` is optional because the codes carry different detail — a
    `side-condition` failure names the proviso, a `slot-unsatisfied` one names the
    slot, and a `hole` adds nothing. Absent means "this code does not carry it".
    """

    code: str
    message: str
    rule: str | None = None
    reference: str | None = None
    lines: list[int] = Field(default_factory=list)
    expected: int | None = None
    given: int | None = None
    slots: list[SlotReportOut] = Field(default_factory=list)
    proviso: str | None = None
    definitions: list[str] = Field(default_factory=list)


class VerifyProofResponse(BaseModel):
    success: bool
    errors: list[str] = Field(default_factory=list)
    proof: dict | None = None
    # The lines stated as open goals rather than proved, by citation number. A
    # proof with holes is *unfinished*, not wrong, and a caller working top-down
    # (or an elaboration loop) needs the difference — `success` is False for both.
    holes: list[int] = Field(default_factory=list)
    # Whether every failing line is a hole: nothing is wrong, there is just work
    # left. False with holes present means both, and the errors come first.
    only_holes: bool = False


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


class ProductionBinding(Binding):
    """A production's slot, which — unlike a rule's or a definition's
    metavariable — may *bind*.

    ``scopes_over`` names the sibling slots this one's binding reaches into:
    ``["phi"]`` for the ``x`` of ``∀x.phi``, empty for an ordinary argument slot.
    Declared, not inferred, because ``∀x.phi`` and a two-argument connective are
    the same shape; what it buys is that a definition whose defining form binds
    need no longer spell out a `fresh` clause — the engine reads it off the
    grammar (see `docs/binding-slots-design.md`).
    """

    scopes_over: list[str] = Field(default_factory=list)


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
    bindings: list[ProductionBinding] = Field(default_factory=list)


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


class Justification(BaseModel):
    """A definition's proof obligation, discharged by citing a settled statement.

    Some definitions hold only because something is *provable* — Metamath's
    `df-sb` defines proper substitution through a dummy variable and is sound just
    because the choice of dummy is immaterial. That is a claim about derivability,
    not about the shape of a term, so it is not a proviso: it is settled once, when
    the system is built, by naming a theorem or premise-free rule whose statement
    is the obligation. See `website.logical.declarative.Justification`.
    """

    # The label of the theorem or rule cited. A stored system carries no proved
    # theorems, so within a spec this names one of its rules.
    label: _Text64
    # The obligation itself, in the system's own grammar, over the definition's
    # own metavariables.
    statement: _Text512


class Definition(BaseModel):
    id: uuid.UUID
    sort: str
    name: str
    higher: str
    lower: str
    # Soundness provisos, one kernel-vocabulary line each (implicit conjunction) —
    # the same structured surface a rule exposes via `side_conditions`.
    provisos: list[str] = Field(default_factory=list)
    bindings: list[Binding] = Field(default_factory=list)
    # The defining form's bound variables (the `fresh` clause). Declaring them lets
    # a quantified definition take the kernel path, so a proviso on it is enforced.
    fresh: list[Binding] = Field(default_factory=list)
    # Optional name a proof cites this definition by (`[<label>, <line>]`); null
    # when unnamed. Unique within a system.
    label: str | None = None
    # The obligation this definition holds only under, or null — which is nearly
    # all of them.
    justification: Justification | None = None


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
    # Where the system came from, when it was not authored here — an import's own
    # sentence, so a reader of one of its proofs can be told whose library it is.
    provenance: str | None = None
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
    # Named notations this system's terms may be *read* through, as against the
    # grammar they are written in. Names only; the templates are served by
    # rendering a proof through one, not by handing the map to a client.
    notations: list[str] = Field(default_factory=list)
    # Which of those a reader is shown first. Null leaves the choice to the
    # client, which prefers a TeX reading where the system has one.
    default_notation: str | None = None


class FormalSystemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str | None = None
    inherits_from_id: uuid.UUID | None = None


class FormalSystemUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    description: str | None = None
    inherits_from_id: uuid.UUID | None = None
    # See declarative.SystemSpec.token_separated. Declaring it holds the system's
    # production templates to it, so a system that means to be token-separated is
    # told where it is not.
    token_separated: bool | None = None
    # Which stored notation a reader is shown first. Null is meaningful — it
    # clears the setting and hands the choice back to the client — so absent and
    # null differ here, and the route reads membership rather than truthiness.
    default_notation: str | None = None
    # True sets published_at to now, False clears it. Absent leaves it unchanged.
    published: bool | None = None


class DefinitionBinder(BaseModel):
    """One bound variable of a definition's defining form, as the engine reads it.

    A projection of the engine's ``kernel.definitions.FreshBinder`` — three field
    reads, no derivation. It exists because `app/` is the HTTP translation layer
    and a Pydantic model is how engine data crosses that boundary, exactly as
    `Production` and `Rule` project their engine counterparts.
    """

    var: str
    sort: str
    # Whether the *engine* worked this binder out rather than the author writing
    # it. Reads `FreshBinder.declared`, which the engine states outright — not its
    # `scoped`, which answers the different question of how far the binder reaches.
    # The two agree today and are not the same fact: placing a *declared* clause by
    # scope would set `scoped` on a binder its author named, and this field would
    # then report their own work back to them as the engine's.
    inferred: bool


class DefinitionBinders(BaseModel):
    """The binders a compiled definition ended up with, for one definition."""

    # The stored definition this reports on. Neither `label` nor `defined_form`
    # identifies a row: a definition may be unnamed, two may share one defined
    # form, and one whose defining form matched nothing is dropped at build — so
    # position in this list does not track position in the stored list either.
    definition_id: uuid.UUID
    # The name a proof cites it by, or null when unnamed.
    label: str | None = None
    # The defined form as the engine renders it — a convenience for display, not
    # an identifier.
    defined_form: str
    binders: list[DefinitionBinder] = Field(default_factory=list)


class SystemValidation(BaseModel):
    """Result of assembling the stored rows and compiling them.

    A system that inherits is compiled against its **whole chain**, so the counts
    below are the effective system's — its ancestors' line types and rules as
    well as its own — which is what a proof written here is checked against.
    `definitions` is the exception, and is scoped to this system's own rows,
    because it carries the `definition_id`s only this system's routes address.
    """

    success: bool
    errors: list[str] = Field(default_factory=list)
    system_name: str | None = None
    # Chain-wide: what the system was built from, not what it declares.
    line_type_count: int | None = None
    inference_rule_count: int | None = None
    # Per compiled definition **of this system**, the `fresh` clause the engine
    # settled on. Only definitions that *layer* appear (one whose defining form
    # matched nothing is dropped at build), so this is a report on what was
    # built, not on what was stored.
    definitions: list[DefinitionBinders] = Field(default_factory=list)


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
    bindings: list[ProductionBinding] = Field(default_factory=list)


class ProductionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    sort: str | None = Field(None, max_length=128)
    template: str | None = Field(None, max_length=512)
    regex: str | None = Field(None, max_length=512)
    atom_value: str | None = Field(None, min_length=1, max_length=512)
    atom_base: str | None = Field(None, min_length=1, max_length=128)
    denotes_constant: bool | None = None
    bindings: list[ProductionBinding] | None = None


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


class _RejectsCondition(BaseModel):
    """Refuses the removed ``condition`` field rather than ignoring it.

    Pydantic drops an unknown field by default, which is the wrong answer for this
    one: a proviso is a *soundness restriction* on definitional unfolding, so a
    pre-`provisos` client would get a 200 and a definition that unfolds where it
    asked for one that does not. Fail the write instead, naming the replacement.

    Scoped to `condition` alone — the rest of the payload keeps the API's ordinary
    tolerance for unknown fields.
    """

    @model_validator(mode="before")
    @classmethod
    def _condition_is_gone(cls, data: object) -> object:
        if isinstance(data, dict) and "condition" in data:
            raise ValueError(
                "'condition' has been removed; send 'provisos' as a list of "
                "kernel-vocabulary lines instead (a ';'-joined condition becomes "
                "one list entry per clause)."
            )
        return data


class DefinitionCreate(_RejectsCondition):
    sort: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=128)
    higher: _Text512
    lower: _Text512
    # Soundness provisos, one kernel-vocabulary line each (implicit conjunction),
    # mirroring rules' `side_conditions`.
    provisos: list[_Text512] = Field(default_factory=list)
    bindings: list[Binding] = Field(default_factory=list)
    # The defining form's bound variables (the `fresh` clause).
    fresh: list[Binding] = Field(default_factory=list)
    # Optional citation name (`[<label>, <line>]`); must be unique within a system.
    label: str | None = Field(None, max_length=64)
    # The obligation this definition holds only under. Both halves travel together
    # — a label with no statement names nothing to check — which is why it is one
    # nested object rather than two columns' worth of flat fields.
    justification: Justification | None = None


class DefinitionUpdate(_RejectsCondition):
    sort: str | None = Field(None, max_length=128)
    name: str | None = Field(None, min_length=1, max_length=128)
    higher: str | None = Field(None, max_length=512)
    lower: str | None = Field(None, max_length=512)
    provisos: list[_Text512] | None = None
    bindings: list[Binding] | None = None
    fresh: list[Binding] | None = None
    label: str | None = Field(None, max_length=64)
    # Nullable and cleared by sending null, like `label`: a definition may stop
    # holding under an obligation.
    justification: Justification | None = None


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

# A promoted theorem's label is cited the same way (`[label]`), so it takes the
# same shape, bounded by what `promoted_theorems.label` stores. Public because
# the promote route derives a *default* label from the proof's slug and has to
# hold it to exactly this rule — a slug is URL-safe, which is a wider alphabet
# and a longer one.
THEOREM_LABEL_PATTERN = _ALIAS_PATTERN
THEOREM_LABEL_MAX = 128


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


class ProofPromotionRequest(BaseModel):
    """Promote a proved proof into its system's library.

    ``label`` is what a later proof cites the theorem by, so it is constrained
    exactly as a reference alias is — the citation grammar reads `[label]` and
    splits on the same delimiters. Omitted, the proof's slug is used.
    """

    label: str | None = Field(
        None, min_length=1, max_length=THEOREM_LABEL_MAX, pattern=THEOREM_LABEL_PATTERN
    )
    # Which leaves of the conclusion stand for *any* term of a sort, rather than
    # for themselves: `{"P": "formula"}` turns the proved `(P → P)` into the
    # theorem `⊢ (φ → φ)`, citable at every instance. Empty promotes the
    # conclusion verbatim, which is a ground theorem justifying only itself.
    #
    # The claim is discharged, not taken: the proof is re-checked with these
    # leaves held schematic, and refused if it no longer stands.
    metavariables: dict[str, str] = Field(default_factory=dict)

    @field_validator("metavariables")
    @classmethod
    def _names_must_fit_storage(cls, value: dict[str, str]) -> dict[str, str]:
        """Bound both halves to what the rows hold.

        A name reaches `promoted_theorem_bindings.var` (`String(128)`) and a sort
        name is resolved against the system's symbols, so an unbounded key is a
        Postgres truncation error at flush — a 500 where this is a 422. Neither
        can be checked for *meaning* here (whether the grammar spells that leaf
        is the engine's answer, and it gives it by refusing the abstracted
        proof); what is checkable is that they fit and are not blank.
        """
        for name, sort in value.items():
            for text, what in ((name, "metavariable"), (sort, "sort")):
                if not text.strip():
                    raise ValueError(f"A {what} name may not be blank.")
                if len(text) > THEOREM_LABEL_MAX:
                    raise ValueError(
                        f"The {what} name {text[:32]!r}… exceeds "
                        f"{THEOREM_LABEL_MAX} characters."
                    )
        return value


class PromotedTheoremOut(BaseModel):
    """A library entry, read back.

    ``statement`` is the conclusion's kernel term rendered, not the source line
    the author typed: promotion takes the term the check ran on, and this is a
    record of it (see `website.logical.promotion.proved_theorem`).
    """

    id: uuid.UUID
    label: str
    statement: str
    formal_system_id: uuid.UUID
    # The proof whose standing warrants the entry — always this proof, for one
    # promoted through the API. Null would mean an imported entry, which no route
    # here returns.
    proved_by_id: uuid.UUID | None = None
    # The assumptions this entry transitively rests on, by label. Empty is the
    # ordinary case and the interesting one is not: an entry with something here
    # is citable, and everything that cites it inherits the debt.
    assumes: list[str] = Field(default_factory=list)
    # Whether this promotion *discharged* an assumption of the same label —
    # replaced a debt with its warrant. Reported because it is not what the
    # caller asked for: it asked to promote, and the label happening to name an
    # assumption is what turned that into paying one off.
    discharged: bool = False


# ---------------------------------------------------------------------------
# Assumptions
# ---------------------------------------------------------------------------


class AssumptionCreate(BaseModel):
    """Take on a citable statement nobody here has proved.

    The statement is written as **source text in the system's own grammar** —
    the same form a corpus import gives a theorem, and the same one
    `website.logical.promotion.promote_from_source` reads. A structured
    (constructor-vocabulary) alternative belongs with goal-first statements
    (docs/informal-source-ingestion-roadmap.md §4.4) and is deliberately not
    guessed at here.
    """

    label: str = Field(
        ..., min_length=1, max_length=THEOREM_LABEL_MAX, pattern=THEOREM_LABEL_PATTERN
    )
    statement: str = Field(..., min_length=1)
    # The hypotheses a citation must supply, and the leaves that stand for any
    # term of a sort — exactly a promoted theorem's, since that is what this is.
    premises: list[str] = Field(default_factory=list)
    metavariables: dict[str, str] = Field(default_factory=dict)
    # Distinct-variable provisos, each a `disjoint(...)` line.
    distinct: list[str] = Field(default_factory=list)
    # Why it is believed true and why it is not proved here. Required: an
    # assumption with no reason is an axiom nobody remembers adopting.
    reason: str = Field(..., min_length=1)
    # Where the claim comes from — an arXiv id, a DOI, a URL, a textbook.
    source: str | None = None


class AssumptionOut(BaseModel):
    """One assumption, and how far it has spread."""

    id: uuid.UUID
    label: str
    statement: str
    reason: str
    source: str | None = None
    formal_system_id: uuid.UUID
    formal_system_name: str
    # Library entries that rest on it **transitively** — an entry three hops
    # away, naming it nowhere, counts. The blast radius, and the ranking that
    # says which gap is worth closing first; a count of direct citers would rank
    # a debt by how visible it is rather than by how much has been built on it.
    #
    # Counts *entries*: a proof that rests on this and has not been promoted is
    # nobody's dependency yet, so it is not counted here.
    dependents: int = 0
    created_at: datetime


class AssumptionDetail(AssumptionOut):
    """The same, with the entries that rest on it named rather than counted."""

    dependent_labels: list[str] = Field(default_factory=list)


class AssumedOut(BaseModel):
    """One assumption, as a dependency report names it."""

    theorem_id: uuid.UUID
    formal_system_id: uuid.UUID
    label: str
    statement: str
    reason: str
    source: str | None = None


class ProofProvenance(BaseModel):
    """What a proof rests on that nobody has proved.

    ``complete`` is the honest half, and there are two ways to lose it — one per
    door into the library. ``unresolved`` names cited **labels** this report
    could not account for (no library entry, no inference rule, no hypothesis of
    a theorem being proved); ``unread_lemmas`` names cited **lemma proofs**
    holding no stored structure, whose own debts could therefore not be read.
    Either dropped silently would let a short list read as a complete one.
    """

    proof_id: uuid.UUID
    assumes: list[AssumedOut] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    unread_lemmas: list[str] = Field(default_factory=list)
    complete: bool = True


class Attribution(BaseModel):
    """One ``(Contributed by NM, 5-Apr-1994.)`` clause, as its three parts.

    Every field verbatim. ``kind`` is an open set — the corpus spells four of them
    wrong and a later revision may add more — and ``dated`` is a string rather
    than a date, because 22 of set.mm's are malformed (``25-Jan-20178``). Both are
    the storage layer's reasoning surfaced unchanged: normalising would mean
    deciding what an upstream typo meant.
    """

    kind: str
    who: str
    dated: str


class LabelReference(BaseModel):
    """One ``~ target`` the prose points at, and where it sits in it.

    ``start``/``end`` index ``LabelDescription.text``, so a client renders the
    reference as a link by **slicing the prose** — it never has to know what a
    Metamath comment looks like. That is why the offsets cross the wire: the
    markup rule lives in the engine, and re-implementing it in the browser would
    be a second copy to keep in step.

    ``proof_id`` is set when the target names a proof in this system and the
    viewer may read it, which is what makes the link navigable; ``title`` is that
    target's own first sentence, for a hover. Both null for a URL, for a label
    naming something that is not a proof (a definition, an axiom), and for the 451
    of set.mm's references that resolve to nothing at all.
    """

    target: str
    start: int
    end: int
    proof_id: uuid.UUID | None = None
    title: str | None = None


class LabelMention(BaseModel):
    """A label whose prose points at the one being read — a reference, backwards."""

    label: str
    proof_id: uuid.UUID | None = None
    title: str | None = None


class LabelClaim(BaseModel):
    """One ``$j`` assertion about a label: ``subject`` is *kind* ``object``.

    ``kind`` is the file's own word, the directive's keyword joined to its
    preposition (`usage_avoids`, `restatement_of`, `primitive`). Deliberately not
    mapped to a vocabulary of ours — a closed set would have to be maintained
    against a file free to add to it, which is the reasoning an attribution's
    ``kind`` follows too. A client that recognises a kind can render it specially
    and one that does not can still show it.

    ``object`` is null for a directive with no preposition, where the claim is
    about the subject alone: `primitive 'wn' 'wi';` is two claims and no object.
    """

    kind: str
    object: str | None = None
    # The object's page, when it names a proof of this system the viewer may open
    # — resolved per read, like a cross-reference's.
    object_proof_id: uuid.UUID | None = None
    object_title: str | None = None


class BibliographyCitation(BaseModel):
    """One ``[Monk1] p. 22`` in a label's prose, with the span it occupies.

    ``work`` is the key as the corpus writes it, and is all there is: the
    bibliography it names lives outside the `.mm` file, so there is no title or
    author to serve. ``page`` is a string — Roman-numbered front matter is cited
    beside ordinary pages.
    """

    work: str
    page: str
    start: int
    end: int


class WorkCited(BaseModel):
    """One work a system's prose cites, and how often."""

    work: str
    citations: int


class WorkCitations(BaseModel):
    """Which of a system's statements cite one work.

    ``cited_by`` carries the same shape a back-reference does — a label, and the
    page to open when there is one — because it is the same kind of answer.
    Capped, with ``cited_by_total`` saying how many there really are.
    """

    work: str
    cited_by: list[LabelMention] = Field(default_factory=list)
    cited_by_total: int = 0


class TheoremCitation(BaseModel):
    """One theorem a proof cites, or one proof that cites it.

    ``label`` is what the citation names; ``proof_id`` is the page to open, null
    when the label has no proof of its own (half a corpus's labels are primitives)
    or when it belongs to a draft the viewer may not read.
    """

    label: str
    proof_id: uuid.UUID | None = None
    title: str | None = None


class ProofCitations(BaseModel):
    """A proof's place in its corpus's citation graph, both directions.

    Distinct from ``ProofDetail.references``/``referenced_by``, which are the
    alias-lemma edges a hand-authored proof declares. These are citations of
    *theorems*, resolved through the library by label — what an imported corpus is
    made of, and what its empty ``proof_references`` does not say. See
    `app.db.citations_mapping` for why the two are not one table.
    """

    cites: list[TheoremCitation] = Field(default_factory=list)
    # Capped, with the true count beside it: `ax-mp` is cited by most of `set.mm`.
    cited_by: list[TheoremCitation] = Field(default_factory=list)
    cited_by_total: int = 0


class LabelDescription(BaseModel):
    """What a system says about one of the labels it names.

    Covers every kind of label alike — a production, a definition, a primitive
    theorem, a proof — because that is how it is stored. ``title`` is the prose's
    first sentence, which is a title in all but name: Metamath declares none.
    """

    label: str
    title: str | None = None
    text: str = ""
    attributions: list[Attribution] = Field(default_factory=list)
    # Where this prose points, in order of appearance.
    references: list[LabelReference] = Field(default_factory=list)
    # And what points back — capped, with `mentioned_by_total` saying how many
    # there really are. See `app.db.descriptions_mapping.mentions_of` on the cap.
    mentioned_by: list[LabelMention] = Field(default_factory=list)
    mentioned_by_total: int = 0
    # `(New usage is discouraged.)` / `(Proof modification is discouraged.)` —
    # markers the corpus puts on a statement, lifted out of the prose so a reader
    # gets a badge rather than a sentence.
    discouraged_usage: bool = False
    discouraged_modification: bool = False
    # Where the prose points *outside* the corpus — the literature a statement was
    # taken from, with the span each citation occupies so a renderer slices rather
    # than re-implements Metamath's markup rule.
    citations: list[BibliographyCitation] = Field(default_factory=list)
    # What the corpus's `$j` markup asserts about this label — that its proof
    # does without `ax-12`, that it restates `axsep`, that it is primitive. The
    # file's claims, not checked ones: nothing here re-derives a proof's
    # transitive dependencies (app/db/claims.py).
    claims: list[LabelClaim] = Field(default_factory=list)


class LabelHit(BaseModel):
    """One label a prose search matched, and where in it the words landed.

    The listing shape beside :class:`LabelDescription`'s single-label one: a
    title, a slice of the prose, and enough to follow the hit. The full record —
    the attributions, the cross-references, what points back — is one read away at
    ``GET /formal-systems/{id}/labels/{label}``, and a search that carried it
    would ship a corpus comment and its whole reference graph per row.
    """

    label: str
    # The layer the label lives on, which on a layered corpus is not the system
    # that was searched. It is what the label is stored against, so it is what a
    # follow-up read has to be addressed to.
    formal_system_id: uuid.UUID
    title: str | None = None
    # The prose around the first matched word, ellipsed where it is a slice. Null
    # when no word landed in the body — always so for a `label` or `title` match,
    # and possible for a `record` one, whose words are spread across fields.
    excerpt: str | None = None
    # The tightest single field holding *every* word — or `record` when no one
    # field holds them all and they are spread across the label, the title and the
    # prose. Served because a ranking a caller cannot account for is one it has to
    # trust blindly or ignore, and this one has a knowable weakness: a common word
    # deep in a long comment ranks exactly like the same word in the title of the
    # thing being looked for.
    matched: Literal["label", "title", "text", "record"]
    # Which of the caller's alternatives found this, as an index into
    # `LabelSearch.searched`. The feedback half of query expansion: a model that
    # proposed five phrasings learns which one the corpus actually uses.
    matched_query: int = 0
    # Set when the label names a proof the viewer may open. Null for the roughly
    # half of a corpus's labels that are `$a`s and have no proof at all — the
    # label is still citable, there is simply nothing to open.
    proof_id: uuid.UUID | None = None
    proof_title: str | None = None
    # `(New usage is discouraged.)` / `(Proof modification is discouraged.)`. On a
    # search result these carry more weight than anywhere else: this is the list a
    # caller picks a citation from, and `set.mm` discourages 5,169 of its own.
    discouraged_usage: bool = False
    discouraged_modification: bool = False


class LabelSearch(Page[LabelHit]):
    """A page of prose hits, how much prose there was to miss, and what was asked.

    ``documented`` is the size of the haystack — how many of this system's labels
    carry any prose at all. It is what makes an empty result readable: "the words
    are not in this corpus" and "this corpus is undocumented" are the same empty
    list otherwise, and only one of them means the search is finished. The same
    distinction ``TheoremMatches.unindexed`` draws, for the same reason.

    ``searched`` is the words actually used — lowercased, deduplicated, and
    capped. The contract is that every one of them appears in every hit, so a
    query past the cap is answered more broadly than it was asked and each extra
    row is a false positive; saying which words ran is what keeps that visible
    rather than silent.
    """

    documented: int
    # One token list per alternative that ran, in the order given.
    searched: list[list[str]]


class ProofSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    # A human sentence beside `name`, which is the proof's identity. They coincide
    # for a hand-authored proof and part ways on an import, where `name` is the
    # label a citation must spell (`sqrt2irr`) and this is what the file's comment
    # opens with.
    title: str | None = None
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
    # The library entry this proof establishes, null until it is promoted.
    theorem: PromotedTheoremOut | None = None
    # What the *system* records about this proof's label — the corpus's own
    # documentation, authorship included, as against `title`/`description`, which
    # are the proof's and are editable. Null when the system describes no such
    # label, which is every hand-authored proof.
    documentation: LabelDescription | None = None


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


class CitationProposal(BaseModel):
    """A justification for one line, proposed as structure rather than as text.

    `{line: 7, rule: "MP", antecedents: [4, 6]}` is a label and three integers —
    already unambiguous, and needing none of the system's citation syntax. That is
    the point: making a client format `[MP, 4, 6]` is exactly where a projection
    creeps back into a structured path (docs/authoring-and-ingestion-roadmap.md §9).

    ``rule`` may be the hole keyword, which parks the line as an open goal — the
    same operation in reverse, and it needs no special case because a hole *is* a
    citation.

    Lines are named by their **citation number**, the same handle an antecedent
    edge uses, not by an index into the source.
    """

    line: int = Field(ge=1)
    rule: _Name128
    antecedents: list[int] = Field(default_factory=list)
    # False — a dry run — because a caller trying several justifications should
    # not have to undo the ones that did not work.
    apply: bool = False


class TermProposalIn(BaseModel):
    """A term named structurally: by reference, or by production.

    Exactly one of ``ref`` and ``constructor``. ``ref`` names a term that already
    exists — the reason this is worth having, since an interned term is shared and
    a caller can point at a subterm instead of restating it. ``constructor`` names
    a production of the system's own grammar, so the vocabulary is closed and
    enumerable.

    A **metavariable is not among them**, though the engine's `Proposal` has one:
    a proof line states a *ground* formula, and a schematic variable belongs to a
    rule schema or a promoted theorem's statement. One proposed here could not
    survive the round trip — `Q` parses back as the grammar's variable
    *production*, not as a `Var` — so it is left out rather than offered and
    refused.
    """

    ref: uuid.UUID | None = None
    constructor: str | None = None
    slots: dict[str, "TermProposalIn"] = Field(default_factory=dict)
    # The token a leaf stands for. A constant atom's comes from the production
    # itself, so it may be omitted there and may not contradict it.
    literal: str | None = None
    # The sort a term *inhabits*, for the one case a term carries it: a defined
    # form, whose constructor is not itself a member of the sort it inhabits.
    sort: str | None = None


class ScopePlacement(BaseModel):
    """Where a new line sits relative to the subproof opened at ``opener``.

    A paper's proof is full of case splits, inductions and "assume for
    contradiction", and every one of them is a **subproof**
    (docs/informal-source-ingestion-roadmap.md §4.6). A subproof is delimited by
    *indentation* — a line indented past an opener is inside it, and one at or
    left of the opener closes it — so placing a line in a subproof means choosing
    its indent, and a caller should not have to know a proof's indent convention
    to do that.

    So the placement is named by the **opener's citation number**, which is what
    a discharge cites anyway and what ``GET /proofs/{id}/structure`` reports:

    * ``inside`` — within that subproof, at the indent its lines already use;
    * ``outside`` — in the scope enclosing it, which is the position a
      **discharge** is written at and the only way to get back out.

    Omitted altogether, a line takes the scope of the line it is anchored to,
    which is what every proposal did before subproofs were reachable.
    """

    opener: int = Field(ge=1)
    placement: Literal["inside", "outside"]


class LineProposal(BaseModel):
    """A new line, stated as structure and justified as structure.

    The expensive half of the structured write path: a citation is a label and
    some integers, but *stating* a formula needs the grammar
    (docs/authoring-and-ingestion-roadmap.md §9).

    ``before`` is the citation number to insert ahead of — which is what a
    goal-directed caller wants, since a rule's antecedents must precede its
    conclusion. Omitted, the line is appended. ``rule`` defaults to the hole
    keyword, because stating a premise you have not proved *is* an open goal.

    ``line_type`` and ``scope`` are the two halves of writing a **subproof**.
    Which line type a line is written as decides whether it *opens* one — a
    system declares that per line type, not per line — and where it is indented
    decides which one it is in. Both default to the anchor line's, so a proposal
    that names neither behaves exactly as it did before they existed.
    """

    statement: TermProposalIn
    rule: _Name128 = "?"
    antecedents: list[int] = Field(default_factory=list)
    before: int | None = Field(default=None, ge=1)
    # Which of the system's line types to write this as. Naming one whose type
    # declares a scope is how a subproof is *opened*; the anchor's own type is
    # used when this is omitted. A type this proof has no line of yet is composed
    # from its declared shape, so the first subproof of a proof is reachable.
    line_type: _Name128 | None = None
    scope: ScopePlacement | None = None
    apply: bool = False


class LineOutcome(BaseModel):
    """What a proposed line would do, or did."""

    # The citation number the new line takes, which is `before` when given.
    line: int
    # The line as it would be written, so a caller sees the source its structure
    # became without reconstructing it.
    display: str
    accepted: bool
    failure: FailureOut | None = None
    # Lines whose citations moved to make room, by their *new* number. Empty for
    # an appended line, which displaces nothing.
    renumbered: list[int] = Field(default_factory=list)
    applied: bool = False
    valid: bool | None = None
    holes: list[int] = Field(default_factory=list)
    only_holes: bool = False
    # Where the line actually landed: the opener of the subproof it is in (null
    # at the proof root), and the kind of scope it opens if it opens one. Read
    # back off the *checked* proof rather than echoed from the request, because
    # indentation is what places a line and a line written at the wrong indent
    # would otherwise report the scope it was meant to join.
    scope: int | None = None
    opens_scope: str | None = None


class LineRemoval(BaseModel):
    """Take a line back out, renumbering what follows.

    The inverse of `LineProposal`, and the one editing operation the structured
    loop was missing: a caller working top-down parks a goal, tries a step, and
    needs to undo it when the step turns out not to be the one
    (docs/authoring-and-ingestion-roadmap.md §9c).

    A dry run unless ``apply``, as the other two are, and owner-only to apply.
    """

    line: int = Field(ge=1)
    apply: bool = False


class LineRemovalOutcome(BaseModel):
    """What removing a line would do, or did."""

    line: int
    # The line as it stood, so a caller can put it back without having kept it.
    removed: str
    # Lines whose citations moved up to close the gap, by their *new* number.
    renumbered: list[int] = Field(default_factory=list)
    applied: bool = False
    valid: bool | None = None
    holes: list[int] = Field(default_factory=list)
    only_holes: bool = False


class CitationOutcome(BaseModel):
    """What a proposed justification would do, or did."""

    line: int
    # The reference text the proposal formats to, so a caller can see what was
    # actually tried without reconstructing it.
    citation: str
    accepted: bool
    # Why not, when not — the same structured reason a verify reports, so a
    # rejected proposal names the next goal rather than only saying no.
    failure: FailureOut | None = None
    applied: bool = False
    # Where the proof stands afterwards. Populated on an applied proposal only:
    # a dry run changed nothing, so reporting a verdict for it would invite
    # reading it as the proof's.
    valid: bool | None = None
    holes: list[int] = Field(default_factory=list)
    only_holes: bool = False


class TermChildOut(BaseModel):
    """One edge below a term node: the slot it fills, and what sits there."""

    slot: str
    id: uuid.UUID


class TermNodeOut(BaseModel):
    """One node of a term subgraph — `TermSummary` plus its edges and reading.

    The fields mirror a ``terms`` row. ``rendered`` is this node read through the
    requested notation, so a caller has the projection *and* the identity of every
    subterm at once: it can point at a formula's part by ``id`` without restating
    it, which is the thing a rendered string alone cannot support.

    ``truncated`` means the walk stopped here with children still below — a
    horizon, not a leaf. ``children`` is reported either way, so a second, deeper
    request can be aimed rather than repeated.
    """

    id: uuid.UUID
    kind: str
    constructor: str | None = None
    literal: str | None = None
    sort: str | None = None
    var_name: str | None = None
    bound_index: int | None = None
    digest: str | None = None
    alpha_digest: str | None = None
    # How far below the requested root this node sits. A DAG node reachable by
    # two paths is reported once, at the shallower of them.
    depth: int
    children: list[TermChildOut] = Field(default_factory=list)
    rendered: str | None = None
    truncated: bool = False


class TermGraphOut(BaseModel):
    """A term's subgraph: every node once, edges by id.

    Flat rather than nested, because a term is an interned **DAG**. A subterm two
    positions share is one row with one id, and nesting would emit it twice —
    losing exactly the structure sharing the storage exists for, and the ability
    to refer to a part rather than repeat it.
    """

    root: uuid.UUID
    formal_system_id: uuid.UUID
    notation: str | None = None
    nodes: list[TermNodeOut] = Field(default_factory=list)
    # Whether any node stopped short of its children (see `TermNodeOut.truncated`).
    truncated: bool = False


class TheoremCandidate(BaseModel):
    """One theorem whose conclusion could be the goal — a candidate, not an answer.

    ``exact`` says the conclusion *is* the goal up to a consistent renaming of its
    variables, so citing it needs no instantiation at all. ``premise_count`` is
    what a caller ranks by after that: a theorem with none can close the goal on
    its own, and one with two needs two standing lines found for it first.

    ``exact`` is a **ranking hint and not a verdict**, for two reasons that both
    matter to a caller tempted to read it as "already proved". It compares the
    stored ``terms.alpha_digest``, whose policy renames every regex leaf — so in
    a grammar whose numerals are a ``matches`` production it reads `2 = 5` and
    `7 = 9` as one statement (`tests/test_alpha_digest.py` pins it); the callers
    that can tell whether their system is one of those report it. And a
    *schematic* theorem that genuinely proves a ground goal is **not** exact,
    since instantiation is unification rather than renaming. Only unification
    against a line in a real scope settles either way.
    """

    label: str
    formal_system_id: uuid.UUID
    # The interned root of the conclusion. A candidate is thus *point-at-able*:
    # feed it to `GET /formal-systems/{id}/terms/{term_id}` to walk the structure,
    # rather than reparse `statement`. `statement` stays the human reading of the
    # same node — identity and projection together, per §9a.
    statement_term_id: uuid.UUID
    statement: str
    primitive: bool
    premise_count: int
    exact: bool = False


class TheoremMatches(BaseModel):
    """What could conclude a goal, narrowed by the shape of its conclusion.

    A **filter's** output, and deliberately not a verdict: every candidate still
    has to unify, and this route does not build the system to find out (see the
    endpoint). What it removes is the 47,589-to-a-handful step that a caller had
    no way to perform at all.

    ``unindexed`` and ``unfiltered`` are what the filter could not see — theorems
    with no cached conclusion term, and whole layers reached through an edge that
    restates or renames past what a root-production filter can ask about. Both are
    reported because a short list is otherwise indistinguishable from a complete
    one.
    """

    formal_system_id: uuid.UUID
    term_id: uuid.UUID
    # The goal's root production, which is what was actually filtered on.
    constructor: str
    candidates: list[TheoremCandidate] = Field(default_factory=list)
    # How many matched before `limit` cut the list.
    matched: int = 0
    truncated: bool = False
    unindexed: int = 0
    # Entries in layers this filter cannot ask about at all — an edge that
    # restates what it carries, or one whose rename leaves this system's
    # production without a pre-image there.
    unfiltered: int = 0


class StatementProposal(BaseModel):
    """A statement named structurally, before there is a proof to put it in.

    §4.4 of docs/informal-source-ingestion-roadmap.md. Every other structured
    write is *inside* a proof; a translation from an informal source needs the
    opposite order — state the target, ask whether it is already proved, and only
    then open a proof aimed at it.

    A **dry run unless ``store``**, as `/cite` and `/lines` are: asking "is this
    proved?" is a question, and a question should not write rows. ``store``
    interns the term and hands back an id — which is what makes it usable as a
    `ref` elsewhere — and is therefore owner-only.
    """

    statement: TermProposalIn
    store: bool = False
    limit: int = Field(25, ge=1, le=200)


class StatementOutcome(BaseModel):
    """A resolved statement, and whether the library already concludes it.

    ``rendered`` is the system's own source spelling, exact by construction: a
    production's render steps *are* its source template. It is what a caller
    would have had to write, handed back after the fact rather than trusted
    before it.

    ``term_id`` is present only when ``store`` was set. Everything else answers
    without writing anything.
    """

    formal_system_id: uuid.UUID
    term_id: uuid.UUID | None = None
    rendered: str
    # The goal's root production — what a search is narrowed by. Null for a
    # statement whose root is a leaf, which names no production and so narrows
    # nothing; ``matches`` is then empty and ``unfiltered`` says the whole library
    # went unasked.
    constructor: str | None = None
    digest: str
    alpha_digest: str
    # Theorems that could conclude it, by the same filter
    # `GET /formal-systems/{id}/theorems/matching` runs — candidates, never a
    # verdict, including the ``exact`` ones. Confirming that one of these really
    # does prove the statement is unification against a line standing in a real
    # scope (`GET /proofs/{id}/lines/{n}/citations`), which is a proof's context
    # and is why no field here says "proved".
    matches: list[TheoremCandidate] = Field(default_factory=list)
    matched: int = 0
    truncated: bool = False
    unindexed: int = 0
    unfiltered: int = 0
    # Whether ``exact`` over-reports in *this* system: true when the grammar
    # declares a regex production whose tokens denote constants, since the stored
    # α-digest renames every regex leaf and so reads `2 = 5` and `7 = 9` as one
    # statement. False for every system that declares none, where `exact` means
    # what it says. Reported rather than left to a caveat, because a caller that
    # cannot tell the two cases apart has to distrust the ranking everywhere.
    exact_is_approximate: bool = False


# ---------------------------------------------------------------------------
# Formalization records — what a formal statement claims to be a formalization of
# ---------------------------------------------------------------------------


class SourceDocumentCreate(BaseModel):
    """Register an external work something here claims to formalize.

    ``version`` is part of the document's identity, not a note about it: a
    paper's v2 may restate the theorem, so a version is a *row* and an existing
    claim keeps pointing at the one its author read. Registering an identity that
    already exists returns the existing row rather than a second one.
    """

    kind: Literal["arxiv", "doi", "isbn", "url", "other"] = "other"
    identifier: str = Field(..., min_length=1, max_length=512)
    version: str = Field("", max_length=64)
    title: str | None = None
    url: str | None = None
    # A digest of the bytes the author actually read. Optional, because a DOI
    # often reaches a paywall rather than a file — and a claim about a paper
    # nobody can hash is worth less, which is worth being able to see.
    content_hash: str | None = Field(None, max_length=128)
    licence: str | None = Field(None, max_length=128)
    retrieved_at: datetime | None = None


class SourceDocument(BaseModel):
    """A registered work, read back.

    ``kind`` is a plain string here where the create model closes the set. The
    column is a free ``String(16)``, so a row written by an import or a fixture
    can carry a kind nobody listed — and a `Literal` on the *output* would fail
    response validation and take the whole listing down with it, which is the
    wrong way to learn that (found in review). Closed for a caller, open for
    data: the same split `Attribution.kind` already makes.
    """

    id: uuid.UUID
    kind: str
    identifier: str
    version: str = ""
    title: str | None = None
    url: str | None = None
    content_hash: str | None = None
    licence: str | None = None
    retrieved_at: datetime | None = None
    created_at: datetime
    # How many claims point at this document.
    formalizations: int = 0


class GlossaryEntryInput(BaseModel):
    """One of the paper's notions, and what it was read as here.

    At least one of ``label`` and ``term_id``: an entry naming nothing records
    only that somebody thought about it.
    """

    notion: str = Field(..., min_length=1, max_length=256)
    label: str | None = Field(None, max_length=128)
    term_id: uuid.UUID | None = None
    reasoning: str | None = None

    @field_validator("notion", "label")
    @classmethod
    def _blank_is_absent(cls, value: str | None) -> str | None:
        """Strip, and read a blank as nothing at all.

        `min_length` counts characters rather than content, so `"   "` satisfies
        it — and an entry whose label is three spaces names exactly as little as
        one with no label. Normalising here means the invariant below is checked
        against what the field *says* rather than against whether it was
        supplied (found in review).
        """
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def _must_name_something(self) -> "GlossaryEntryInput":
        if self.notion is None:
            raise ValueError("A glossary entry must name the notion it is about.")
        if self.label is None and self.term_id is None:
            raise ValueError(
                f"The glossary entry for {self.notion!r} names nothing it was "
                "read as. Give a label or a term id."
            )
        return self


class GlossaryEntry(GlossaryEntryInput):
    id: uuid.UUID


class FormalizationCreate(BaseModel):
    """Claim that a term is a formalization of a result in a document.

    ``reasoning`` is required and is the point: a claim with no argument is a
    tick, and the one thing this layer exists to refuse is a tick. ``attested_as``
    names the agent that did the reading where that was not a person — a model
    identifier — recorded *beside* the account rather than instead of it, since
    an account is accountable and a model is not.
    """

    document_id: uuid.UUID
    claim: str = Field(..., min_length=1, max_length=256)
    informal_statement: str = Field(..., min_length=1)
    formal_system_id: uuid.UUID
    statement_term_id: uuid.UUID
    proof_id: uuid.UUID | None = None
    reasoning: str = Field(..., min_length=1)
    attested_as: str | None = Field(None, max_length=128)
    glossary: list[GlossaryEntryInput] = Field(default_factory=list)

    @field_validator("claim", "informal_statement", "reasoning")
    @classmethod
    def _must_say_something(cls, value: str) -> str:
        """Content, not characters.

        `min_length` counts the latter, so `"   "` passes it — which would admit
        exactly the empty attestation this schema exists to refuse, and the
        disputed-review validator below already knew better (found in review).
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("This field may not be blank.")
        return stripped


class FormalizationReview(BaseModel):
    """A second person's verdict on a claim.

    ``disputed`` requires a note, because a dispute nobody explained is not a
    finding — and a dispute is the more valuable of the two verdicts.
    """

    verdict: Literal["confirmed", "disputed"]
    note: str | None = None

    @model_validator(mode="after")
    def _a_dispute_says_why(self) -> "FormalizationReview":
        if self.verdict == "disputed" and not (self.note or "").strip():
            raise ValueError("A disputed review must say what is wrong with the claim.")
        return self


class Formalization(BaseModel):
    """One claim, read back.

    ``reviewed`` is deliberately not a boolean the row carries: it is null until
    somebody who is not the attestor has said something, and then it is what they
    said. An unreviewed claim is the ordinary state and is meant to look like one.
    """

    id: uuid.UUID
    document: SourceDocument
    claim: str
    informal_statement: str
    formal_system_id: uuid.UUID
    statement_term_id: uuid.UUID
    # Read it with `GET /formal-systems/{id}/terms/{term_id}`, which is the route
    # that renders a stored term — through a chosen notation, with every subterm's
    # id beside its reading. Not duplicated here: a term row is structure and
    # carries no display, so the source spelling needs the system *built*, which
    # is 55 ms on a corpus grammar and would be paid per system per listing to
    # serve something lossier than the route that already exists.
    proof_id: uuid.UUID | None = None
    reasoning: str
    attested_by: SystemOwner | None = None
    attested_as: str | None = None
    attested_at: datetime
    # A plain string for the same reason `SourceDocument.kind` is: the column is
    # free text, and a read must not fail on a value it did not expect.
    review_verdict: str | None = None
    review_note: str | None = None
    reviewed_by: SystemOwner | None = None
    reviewed_at: datetime | None = None
    glossary: list[GlossaryEntry] = Field(default_factory=list)


class CitationSuggestion(BaseModel):
    """A justification that **checks**, ready to be sent back to `/cite`.

    Not a guess: each of these was confirmed by the same unification and proviso
    check a verify runs, against the lines that actually stand above the goal. The
    fields are exactly `CitationProposal`'s, so acting on one is a copy rather
    than a translation.

    ``source`` says whether the justification is one of the system's own inference
    rules or an entry from its library — a distinction of *where it came from*,
    not of how it was checked, since a promoted theorem is cited exactly as a rule
    is.
    """

    rule: str
    antecedents: list[int] = Field(default_factory=list)
    # The reference text this formats to, so a caller can show its work.
    citation: str
    source: Literal["rule", "theorem"]
    # Whether the cited line is a subproof opener rather than an antecedent —
    # the same citation shape, a different thing being cited.
    discharge: bool = False
    exact: bool = False
    # Whether this rule justifies *any* line (a hypothesis rule). True, and a
    # fact about the system rather than about this goal — so it is reported and
    # ranked last rather than dropped, since assuming the line is sometimes
    # exactly what an author means to do.
    assumption: bool = False


class CitationSearch(BaseModel):
    """Justifications found for one line, and how much was looked at.

    The move the loop was missing. `slot-unsatisfied` says which premise is
    missing and a hole says what is left to prove; neither says *what to cite*,
    and this does — as proposals that have already been checked, so a caller can
    apply one rather than trying it.

    ``scanned`` is the honest accounting: how many rules were tried, how many
    library candidates the prefilter offered, how many it could not see, and
    whether a limit cut the list. A search that quietly stopped early would
    otherwise read as one that found everything there was.
    """

    line: int
    suggestions: list[CitationSuggestion] = Field(default_factory=list)
    rules_tried: int = 0
    candidates_tried: int = 0
    # Library entries the prefilter could not reach (no cached conclusion term).
    unindexed: int = 0
    # Library entries in a layer the prefilter cannot ask about at all; see
    # `TheoremMatches.unfiltered`.
    unfiltered: int = 0
    # Whether anything was cut: more justifications were found than `limit`, or
    # the prefilter matched more candidates than it was allowed to offer. Either
    # way there may be more, which is the only thing a caller can act on.
    truncated: bool = False


class LibraryEntry(BaseModel):
    """What a citation's label names, read from rows alone.

    The cheap half of `LineJustification`. That record re-checks the proof,
    because the substitution it reports is derived by the match and no row
    carries it — which is why it is signed-in only (see `explain_line`). But
    almost everything a reader wants from a citation is *not* derived: what
    `imbi12d` says, what it needs, what the corpus records about it and where its
    proof is are all stored, and asking for them costs a handful of indexed row
    reads.

    So they are served separately, and to anyone who may read the system. A
    reader of a published corpus gets the answer to "what is this step citing";
    what signing in adds is what the metavariables stood for *here*.
    """

    label: str
    # The rule's own name where it has one (`modus ponens`); empty for a library
    # entry, which is named by its label alone.
    name: str = ""
    # "rule" — a primitive this system declares — or "theorem", an entry of its
    # library. `primitive` on a library entry makes the same split within it, and
    # is reported as "axiom".
    kind: str
    conclusion: str
    premises: list[str] = Field(default_factory=list)
    # The subproof a discharge rule consumes, as its schema reads.
    discharges: str | None = None
    title: str | None = None
    proof_id: uuid.UUID | None = None
    # The notation the schemas above were read through, echoed as `ProofStructure`
    # echoes it: a client showing a proof in one spelling must be able to tell a
    # served rendering from a silently ignored request.
    notation: str | None = None


class JustifyingPremise(BaseModel):
    """One antecedent of the rule, and the line that filled it.

    ``schema_form`` is the rule's own — what it demands of that slot — and the
    rest is what the step supplied. Empty for a line the rule did not ask for and
    tolerated (``extra``), which fills no slot.
    """

    position: int
    schema_form: str = ""
    number: int | None = None
    statement: str | None = None
    extra: bool = False


class JustifyingAssignment(BaseModel):
    """What one of the rule's metavariables stood for on this step."""

    variable: str
    stands_for: str


class JustifyingProviso(BaseModel):
    """A side-condition the step had to satisfy, in the author's own words.

    ``variables`` are the metavariables it mentions, so a reader can find them
    among the assignments and see what it was about. The instantiated condition
    is deliberately not composed — see `website.logical.formal_system.justification`.
    """

    source: str
    variables: list[str] = Field(default_factory=list)


class LineJustification(BaseModel):
    """Why one line follows, as a reader can check it.

    `Failure` says why a line did *not* check; this is the other half, and the
    citation on the line — `[imbi12d, 2, 3]` — is all a reader had of it. What
    the checker established is the rule the label resolved to, that rule's own
    schemas, which cited line filled which premise, and the substitution the
    match derived.

    ``proof_id`` is the proof establishing the cited theorem, when the viewer may
    read one: a library citation names a label, and the proof of that label is a
    row away but is not something a client can find by itself.
    """

    line: int
    citation: str | None = None
    # "rule" — an inference rule or a promoted theorem, which are one shape to
    # the checker — or "definition" for a definitional step, which cites neither.
    kind: str
    label: str
    name: str
    conclusion: str
    premises: list[JustifyingPremise] = Field(default_factory=list)
    assignments: list[JustifyingAssignment] = Field(default_factory=list)
    provisos: list[JustifyingProviso] = Field(default_factory=list)
    # The subproof a discharge rule consumed, as its schema reads; null for every
    # other kind of step.
    discharges: str | None = None
    # The corpus's own one-line summary of the cited label, where it documents
    # one — on an import the label is opaque and this is the readable name.
    title: str | None = None
    proof_id: uuid.UUID | None = None
    # The notation the terms here were read through, echoed as `ProofStructure`
    # echoes it: a client showing a proof in one spelling must be able to tell a
    # served rendering from a silently ignored request.
    notation: str | None = None


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
    # The same verdict as data: a code a caller can branch on, plus what the
    # checker knew. `code == "hole"` is an open goal rather than a mistake.
    failure: FailureOut | None = None
    warning_message: str | None = None
    # The line's formula re-spelled in the requested notation, or null when none
    # was asked for or the line bears no formula. `display` is left alone: it is
    # the source the proof was written in, and the two are different questions.
    #
    # Narrower than `display` in one more way — this is the *term*, so it carries
    # no citation. A client showing a notation writes the citation itself, from
    # `reference` and `rule`.
    rendered: str | None = None
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
    # The notation the lines were rendered through, echoed so a client can tell a
    # served rendering from a silently ignored request. Null when none was asked
    # for; a name the system does not store is a 404 rather than a null.
    notation: str | None = None


# ---------------------------------------------------------------------------
# Relations between systems — the general edge (R4 of the relationships roadmap)
# ---------------------------------------------------------------------------


class SystemRelationRename(BaseModel):
    """One entry of an edge's sort or symbol map: ``source`` is read as ``target``.

    Both are grammar **names**, not ids: the whole point of a map is that the two
    systems' namespaces are separate, so there is no id to share. Absent entirely
    for the identity, which is what an edge between systems that agree on their
    vocabulary carries.
    """

    source: _Name128
    target: _Name128


class SystemRelationExtra(BaseModel):
    """One metavariable the statement template introduces — ``Γ : context``.

    ``sort`` names one of the **target's** sorts: the template is read against
    the grammar of the system gaining the theorems, not the one that proved
    them. These are not renames of anything — a sequent's antecedent has no
    counterpart in the Hilbert formula being wrapped.
    """

    name: _Name128
    sort: _Name128


class SystemRelationObligationIn(BaseModel):
    """One primitive of the source, and what stands in for it here.

    Exactly one of the two discharge fields is set — a rule of the target under
    some label, or a theorem it has proved — and ``status`` says whether the
    author considers it settled. See `app/db/system_relations.py`.
    """

    source_label: _Name128
    discharged_by_primitive: _Name128 | None = None
    discharged_by_theorem_id: uuid.UUID | None = None
    status: RelationStatus = "draft"


class SystemRelationObligation(SystemRelationObligationIn):
    id: uuid.UUID


class SystemRelationCreate(BaseModel):
    """A new edge into the system named in the path, which is its **target**.

    The target is the system that gains citable theorems, and its owner is
    therefore the one who may say so — an edge is a claim about what this
    system's proofs may rest on.
    """

    source_system_id: uuid.UUID
    kind: RelationKind = "extension"
    status: RelationStatus = "draft"
    # How this system restates a transferred theorem, when it states a different
    # *kind* of thing than the source does: `'G ⊢ {wff}'`, whose one brace-marked
    # hole names the sort the transferred statement is read at here. Absent for
    # every edge between two systems that agree about what a judgement is.
    statement_template: str | None = Field(None, max_length=512)
    sorts: list[SystemRelationRename] = Field(default_factory=list)
    symbols: list[SystemRelationRename] = Field(default_factory=list)
    extras: list[SystemRelationExtra] = Field(default_factory=list)
    obligations: list[SystemRelationObligationIn] = Field(default_factory=list)


class SystemRelationUpdate(BaseModel):
    """A partial edit. A collection given is replaced whole, as a rule's is.

    ``source_system_id`` is deliberately absent: repointing an edge is deleting
    one relationship and asserting another, and the two have different
    obligations. Delete and create.
    """

    kind: RelationKind | None = None
    status: RelationStatus | None = None
    # Which edge wins a label two of them offer; lower first, ties by id.
    position: int | None = Field(None, ge=0)
    # Cleared by the empty string rather than by `None`, which here means "leave
    # it alone" as it does for every other field of a partial edit.
    statement_template: str | None = Field(None, max_length=512)
    sorts: list[SystemRelationRename] | None = None
    symbols: list[SystemRelationRename] | None = None
    extras: list[SystemRelationExtra] | None = None
    obligations: list[SystemRelationObligationIn] | None = None


class SystemRelation(BaseModel):
    id: uuid.UUID
    source_system_id: uuid.UUID
    # Echoed so a list of edges reads without a lookup per row; a source may be
    # someone else's published system, whose name is public.
    source_system_name: str
    target_system_id: uuid.UUID
    kind: RelationKind
    status: RelationStatus
    position: int
    statement_template: str | None = None
    sorts: list[SystemRelationRename] = Field(default_factory=list)
    symbols: list[SystemRelationRename] = Field(default_factory=list)
    extras: list[SystemRelationExtra] = Field(default_factory=list)
    obligations: list[SystemRelationObligation] = Field(default_factory=list)
    # Whether this edge currently transfers anything, and why not if it does not.
    # A `draft` edge and one with an outstanding obligation both resolve nothing,
    # and neither is an error — so this reports rather than refuses.
    resolves: bool = False
    outstanding: list[str] = Field(default_factory=list)


class Folder(BaseModel):
    """One node of a system's folder tree, with everything under it.

    An imported corpus fills this from the section headers its `.mm` file draws
    (`####` part, `#*#*` section, `=-=-` subsection, `-.-.` subsubsection): the
    depth *is* the nesting, so the level is not a field — it is where the node
    sits. `description` is the prose a header carries after its title.

    ``proofs`` counts what sits directly in this folder, not in the whole subtree:
    a corpus's part-level node holds nothing itself and thousands beneath it, and
    reporting the subtree total would make every ancestor look equally full.
    """

    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    position: int
    proofs: int = 0
    children: list["Folder"] = Field(default_factory=list)


Folder.model_rebuild()


class ProofCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    # The system this proof is written against; must be owned by the caller.
    formal_system_id: uuid.UUID
    # Optional, and normally left unset when authoring: `name` is already the
    # human one. It earns its keep where identity and sentence differ, which an
    # import is and a hand-authored proof usually is not.
    title: str | None = None
    description: str | None = None
    source: str = ""


class ProofUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    title: str | None = None
    description: str | None = None
    source: str | None = None
    # True sets published_at to now, False clears it. Absent leaves it unchanged.
    published: bool | None = None
