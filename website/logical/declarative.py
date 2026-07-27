"""A declarative model of a formal system, built directly into the engine.

This is the only way a formal system is built. It replaced a bespoke source
language (``.edi``, since deleted) that forced three unrelated jobs -- the
*grammar*, the *inference rules*, and *side conditions* -- through one
whitespace-sensitive mechanism, and in which a recursive grammar only worked if
the author performed a non-obvious ordering dance (forward-declare an empty
``UnionPattern`` *then* fill it); a wrong guess compiled cleanly and silently
matched nothing.

What replaced it is a structured, order-independent description of a system --
the :class:`SystemSpec` dataclasses (grammar productions, a logical line,
definitions, axioms, rules). :func:`build_spec` / :func:`build_system` turn one
into a ``FormalSystem`` **directly**, by calling the engine's own construction
primitives (``build_schema_pattern``, ``add_variables``, ``add_notation``,
``parse_side_condition``, the ``Pattern`` constructors) -- no text pass. Nothing
here re-implements matching or proof checking; it only wires the declarative
model into engine objects. Because there is no text pass, ``respect_brackets``
is set on each pattern at construction.

A :class:`SystemSpec` is built by the persistence layer
(``app.db.system_to_spec`` reconstructs one from stored rows) or, in tests, by
scripted assembly. The relational storage, not a source blob, is the source of
truth.

Crucially, **definitions remain first-class**: a definition becomes the engine's
``Define <higher> as <lower> [where <proviso>]``, so a complex base system (ZFC)
can be layered up with familiar notation (``⊆``, ``∅``, ``P(x)`` ...) exactly as
the engine already supports.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from copy import copy
from dataclasses import InitVar, dataclass, field, replace
from typing import TYPE_CHECKING

from .build_context import (
    FormalSystemContext,
    build_schema_pattern,
    combine_side_conditions,
)
from .formal_system import (
    FormalSystem,
    InferenceRule,
    LineType,
    SubproofSchema,
    statement_term,
)
from .formal_system.definitions import (
    DefinitionError,
    build_kernel_definition,
    denotes_a_constant,
)
from .formal_system.side_condition_syntax import parse_side_condition
from .kernel import And, match, references, restate
from .kernel.constructors import constructor_for, project_grammar
from .matching import AtomPattern, Pattern, RegexPattern, StringPattern, UnionPattern
from .promotion import promote_from_source

if TYPE_CHECKING:
    from .kernel import SideCondition
    from .kernel.constructors import Constructor
    from .kernel.definitions import Definition as KernelDefinition
    from .matching.definitions import DefinedNotation


class DeclarativeError(Exception):
    """Raised for problems detectable in a :class:`SystemSpec` before lowering."""


# The scopes a line type may open (mirrors LineType.scope's accepted values).
_LINE_SCOPES = (None, "assumption", "variable")

# The line behaviours a declarative system may author. `LineType` accepts one
# more - `axiom` - which is emitted from `spec.axioms` rather than declared on a
# line, so offering it here would give two ways to say the same thing. Keep this
# in step with `app.schemas.LineBehaviour`, the API's mirror of it.
_LINE_BEHAVIOURS = ("logical", "comment")


# ---------------------------------------------------------------------------
# Structured records: the declarative model of a system
# ---------------------------------------------------------------------------


@dataclass
class Production:
    sort: str
    name: str
    template: str | None = None        # composite: the notation template
    regex: str | None = None           # atomic (leaf): a raw regex
    atom_value: str | None = None      # atom constant: the single literal token it matches
    atom_base: str | None = None       # atom family: base of the `p_#` indexed family
    bindings: list[tuple[str, str]] = field(default_factory=list)  # (var, sort)
    # Whether this production's tokens are *constants* of the object language —
    # one fixed denotation, never standing for a bound variable — as opposed to
    # variables of it. This is Metamath's `$c` vs `$v`, and like Metamath's it is
    # declared, not inferred: no property of a production's shape decides it. A
    # single-token atom is a constant in `formula ::= ⊥` and a variable in
    # `setvar ::= a | b | c`, and only the author knows which was meant.
    #
    # Consulted for one purpose: whether a definition's defining form may
    # introduce this token without the defined form supplying it (see
    # `formal_system.definitions.build_kernel_definition`). Defaults to False —
    # variable-like — so omitting it costs a refused definition, never a
    # capturing one.
    denotes_constant: bool = False
    # Which of this production's slots *bind*, and over what: a binding's `var`
    # mapped to the sibling vars it scopes over. `∀x phi` declares
    # `{"x": ["phi"]}`. Empty — the default — means the production says nothing
    # about binding, which is what every production said before this field
    # existed and is read exactly as it was then.
    #
    # Declared, like `denotes_constant`, and for the same reason: `∀x phi` and a
    # two-argument connective are the same shape. What it buys is that a
    # definition's `fresh` clause need no longer be written by hand — a leaf
    # sitting in a binder slot of the defining form *is* a binder, and
    # `formal_system.definitions` reads it off the parsed term. See
    # docs/binding-slots-design.md.
    scopes_over: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Justification:
    """A proof obligation a definition carries, discharged by citing a theorem.

    Some definitions hold only because something is *provable*. Metamath's
    `df-sb` defines proper substitution through a dummy `y` that appears on the
    right only, and is sound just because the choice of `y` is immaterial; its
    hypothesis `sbjust.1` is the statement that it is.

    That is not a proviso and cannot become one. Every predicate in the kernel's
    closed algebra is a total structural check on *shape*, while this is a claim
    about *derivability*: a `Proven(φ)` condition would have to search for a proof
    at every citation, which is undecidable and would restore the executable
    condition language the kernel retired.

    So it is discharged once, when the definition is registered, by naming a
    theorem already proved in the system whose statement is the obligation -
    which is what Metamath does too, since `sbjust` is a proved `$p` preceding
    `df-sb` and stating exactly its hypothesis. ``statement`` is the obligation in
    the system's own grammar, over the definition's own metavariables; ``label``
    names the promoted theorem that settles it.

    When it is *not* needed
    -----------------------
    An obligation of `df-sb`'s particular kind - "the dummy could have been any
    name" - is an artefact of writing definitions with named binders. Declare the
    dummy `fresh` and the kernel stores it abstractly
    (:class:`~website.logical.kernel.terms.Bound`), so the definition makes no
    choice of name and there is nothing left to justify: both spellings are unfolds
    of one defined form, and their equivalence follows rather than precedes.

    That is not a reason to drop this. `set.mm` states the argument itself, in
    `df-sb`'s comment - *"Without this hypothesis, sbjust would be derivable from
    propositional axioms alone: one could apply the definiens twice, using
    different dummy variables"* - and keeps the hypothesis anyway, because making
    `sbjust` derivable would weaken an independence claim about its axioms. So the
    two routes import the same theorems under different metatheoretic discipline,
    and a faithful import wants this one. The obligations it is really *needed*
    for are the ones no representation removes: an existence lemma of the
    `df-div`/`df-sqrt` kind (roadmap A4).
    """

    label: str
    statement: str


@dataclass
class Definition:
    sort: str
    name: str
    higher: str
    lower: str
    bindings: list[tuple[str, str]]
    # Soundness provisos (the `where` clause), `;`-separated kernel-vocabulary
    # lines. Checked at every unfold against what that unfold binds, so a proviso
    # may name a parameter of the *defined* form or one of the `fresh` binders
    # below (by its declared name — a binder is stored abstractly, so the proviso
    # constrains whatever leaf it takes there). Naming anything else is refused at
    # build: there would be nothing to resolve it against.
    condition: str | None = None
    # The defining form's bound variables, `[(var, sort)]` (the `fresh` clause).
    # Declaring a binder lets the term checker unfold the definition
    # capture-avoidingly, so a quantified definition (and any proviso on it) takes
    # the kernel path instead of being refused. Empty for a binder-free alias.
    fresh: list[tuple[str, str]] = field(default_factory=list)
    # Optional name a proof cites this definition by (`[<label>, <line>]`); the
    # generic `[Def, <line>]` keyword searches all in-scope definitions instead.
    # Must be unique within a system so a named citation resolves unambiguously.
    label: str | None = None
    # The obligation this definition holds only under, discharged by citing an
    # already-proved theorem when the system is built. None — the default — is a
    # definition that holds outright, which is nearly all of them.
    justification: Justification | None = None


@dataclass
class Subproof:
    """The subproof a discharge rule consumes as a unit (→I, RAA, ∀I).

    A discharge rule cites no lines: it consumes a whole subproof. ``derive`` is
    the pattern its final line must match; the subproof is opened by exactly one
    of ``assume`` (a hypothesis pattern, an *assumption* subproof) or ``fresh``
    (an eigenvariable pattern, a *variable* subproof). All three are rule-schema
    source lines, parsed against the rule's metavariables like its deduction.
    """
    derive: str
    assume: str | None = None
    fresh: str | None = None


@dataclass
class Rule:
    label: str
    name: str
    antecedents: list[str]
    deduction: str
    bindings: list[tuple[str, str]]
    # Soundness provisos from the `side_conditions` section, one kernel-vocabulary
    # line each (implicit conjunction). Attached to the rule by its label; empty
    # for axioms and unconditioned rules.
    side_conditions: list[str] = field(default_factory=list)
    # How steps are checked against this rule: "structural" (term unification,
    # the default) or "string" (associative matching, for a string-rewriting
    # rule such as MIU's — see website.logical.matching.rewriting).
    matching: str = "structural"
    # The subproof this rule discharges, or None for an ordinary line-antecedent
    # rule. A discharge rule typically has no `antecedents`.
    subproof: Subproof | None = None
    # Whether a citation may name *more* lines than the rule has antecedent slots.
    # The surplus lines are recorded as `extra_antecedents` and left unconstrained
    # (they justify nothing), so this weakens what the citation must prove; off by
    # default, so a citation must name exactly the rule's antecedents.
    #
    # Inert on a discharge rule: that path cites exactly one subproof opener and
    # never consults this flag. Unlike antecedents/side-conditions (which the
    # discharge check also ignores, but whose loss would drop a *soundness*
    # constraint, hence the guard in build_system), an ignored allowance can only
    # ever be stricter, so the pairing is permitted rather than rejected.
    allow_extra_antecedents: bool = False


@dataclass
class LinePart:
    name: str
    regex: str


@dataclass
class LineSpec:
    name: str
    shape: str
    parts: list[LinePart] = field(default_factory=list)
    logical_sort: str | None = None
    # The scope this line opens, orthogonal to its logical behaviour: None (a
    # plain line), "assumption" (opens a subproof under a hypothesis, for e.g.
    # →I) or "variable" (opens one under a fresh variable, for e.g. ∀I). A scope
    # opener may still bear a formula, so this is separate from the line's shape.
    scope: str | None = None
    # What the checker does with lines of this type: "logical" (the default — the
    # line asserts a formula and must be justified) or "comment" (prose, never
    # checked and never numbered, so no citation can name it). A comment line
    # carries no formula, so it needs no `logical_sort` and its shape need not
    # name a grammar sort — the one line kind that may be pure text.
    behaviour: str = "logical"


@dataclass
class SystemSpec:
    name: str = ""
    brackets: list[tuple[str, str]] = field(default_factory=list)
    # Whether every token of this system's notation is written whitespace-
    # separated, as Metamath's is (`( ph -> ps )`, never `(ph->ps)`).
    #
    # Declared rather than inferred: it is a claim about how proofs will be
    # *written*, which no set of templates settles. Nothing depends on it being
    # true - a constant spelled with a bracket is read correctly either way,
    # because `Pattern._opaque_positions` decides token by token rather than
    # trusting the system (and a glued system simply cannot write such a
    # constant glued). What declaring it buys is that the production templates
    # are then held to it, so a system meaning to be token-separated is told
    # where it is not.
    token_separated: bool = False
    productions: list[Production] = field(default_factory=list)
    # Logical line types, in order. A system typically has one (`statement`), but
    # may declare several (e.g. a `claim` line and a scoped `assume` line); the
    # engine tries each when parsing a proof line.
    lines: list[LineSpec] = field(default_factory=list)
    definitions: list[Definition] = field(default_factory=list)
    axioms: list[Rule] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    # Back-compat for the former single-line API (`SystemSpec(line=...)`). An
    # `InitVar` so it is accepted at construction but never a stored field —
    # otherwise it would perturb the dataclass `==` the storage round-trip relies
    # on. Prefer `lines`.
    line: InitVar[LineSpec | None] = None

    def __post_init__(self, line: LineSpec | None) -> None:
        if line is not None:
            self.lines = [line, *self.lines]

    def sort_names(self) -> list[str]:
        seen = []
        for p in self.productions:
            if p.sort not in seen:
                seen.append(p.sort)
        return seen


# ---------------------------------------------------------------------------
# Shared helpers for turning spec fields into engine objects
# ---------------------------------------------------------------------------


def _identifier(name: str) -> str:
    ident = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    if ident and ident[0].isdigit():
        ident = "_" + ident
    return ident


def _anchor(regex: str) -> str:
    if not regex.startswith("^"):
        regex = "^" + regex
    if not regex.endswith("$"):
        regex = regex + "$"
    return regex


def _line_layout(
    line: LineSpec, sorts: set[str],
) -> tuple[str, list[tuple[str, str]], tuple[str, str] | None, tuple[str, str] | None]:
    """Resolve a line's template and its formula/reference placeholders.

    Returns ``(template, placeholders, logical_ph, reference_ph)`` where each
    ``_ph`` is a ``(placeholder_name, variable)`` pair (either may be ``None``),
    given the system's grammar ``sorts`` so the logical placeholder can be
    resolved. ``logical_ph`` is ``None`` only for a comment line, which carries
    no formula.
    """
    part_names = {p.name for p in line.parts}

    # Tokenise the shape into (placeholder | literal) fragments.
    template, placeholders = _shape_to_template(line.shape)

    # Every placeholder has to resolve to something later (`ctx.variables[ph]`),
    # so name the undeclared one here rather than letting it surface as a bare
    # KeyError whose message is just the token.
    undeclared = [ph for ph, _ in placeholders if ph not in part_names and ph not in sorts]
    if undeclared:
        raise DeclarativeError(
            f"Line {line.name!r} has placeholder(s) "
            f"{', '.join(repr(ph) for ph in undeclared)} in its shape naming no "
            f"grammar sort or part; declare each as a part of the line."
        )

    # A comment line asserts nothing, so it has no formula to project — and its
    # shape is free to be prose, naming no grammar sort at all.
    if line.behaviour == "comment":
        if line.logical_sort is not None:
            raise DeclarativeError(
                f"Line {line.name!r} is commentary, so it carries no formula; "
                f"remove its logical sort {line.logical_sort!r}."
            )
        # Nor a citation. Projecting the prose as the line's `reference` would
        # surface it in the UI as the rule that justified the line.
        return template, placeholders, None, None

    # Choose the logical placeholder: explicit 'logical <sort>' or first sort.
    logical_ph = None
    if line.logical_sort:
        for ph, var in placeholders:
            if ph == line.logical_sort:
                logical_ph = (ph, var)
                break
    if logical_ph is None:
        for ph, var in placeholders:
            if ph in sorts:
                logical_ph = (ph, var)
                break
    if logical_ph is None:
        raise DeclarativeError("Line shape must contain a placeholder naming a grammar sort.")

    # The reference placeholder (if any inline part is used).
    reference_ph = None
    for ph, var in placeholders:
        if ph in part_names:
            reference_ph = (ph, var)
            break

    return template, placeholders, logical_ph, reference_ph


def _shape_to_template(shape: str) -> tuple[str, list[tuple[str, str]]]:
    # Replace each <name> placeholder with a fresh single-letter variable,
    # preserving all literal text (spaces, brackets) verbatim.
    template = []
    placeholders: list[tuple[str, str]] = []
    used = set()
    i = 0
    while i < len(shape):
        if shape[i] == "<":
            j = shape.find(">", i)
            if j == -1:
                raise DeclarativeError(f"Unclosed placeholder in shape: {shape!r}")
            ph = shape[i + 1:j]
            var = _fresh_var(ph, used)
            used.add(var)
            placeholders.append((ph, var))
            template.append(var)
            i = j + 1
        else:
            template.append(shape[i])
            i += 1
    return "".join(template), placeholders


def _fresh_var(placeholder: str, used: set[str]) -> str:
    base = placeholder[0] if placeholder else "v"
    if base not in used:
        return base
    n = 1
    while f"{base}{n}" in used:
        n += 1
    return f"{base}{n}"


# ---------------------------------------------------------------------------
# Direct builder: SystemSpec -> FormalSystem.
#
# This constructs the engine objects straight from the SystemSpec by calling the
# engine's own low-level primitives (build_schema_pattern, add_variables,
# add_notation, parse_side_condition, the Pattern constructors), driven from
# the spec fields directly. There is no text pass, so respect_brackets is set on
# each pattern at construction rather than patched on afterwards.
# ---------------------------------------------------------------------------


def _bracket_map(spec: SystemSpec) -> dict[str, str] | None:
    # The opening->closing map every pattern respects: declared pairs, else the
    # default `()` when any template/definition/deduction actually uses a paren.
    brackets = list(spec.brackets)
    if not brackets and _uses_parens(spec):
        brackets = [("(", ")")]
    return {o: c for o, c in brackets} or None


def _bracket_opaque_tokens(
    spec: SystemSpec, brackets: dict[str, str] | None
) -> tuple[str, ...]:
    # Declared constants that *contain* a bracket delimiter without being one.
    # Whether a character groups is a property of the grammar, not of the
    # character, and only the grammar knows which of its tokens merely spell one:
    # set.mm names its half-open intervals `[,)` and `(,]`, so `( 0 [,) +oo )`
    # counts three closing brackets against two openings and reads as unbalanced.
    # Sorted for a deterministic order only. Overlap needs no care from the
    # caller: `_opaque_positions` unions the spans of *every* occurrence of
    # *every* token, so one token containing another (set.mm has `O(1)` inside
    # `<_O(1)`) covers the same indices whichever is seen first.
    if not brackets:
        return ()

    delimiters = (*brackets, *brackets.values())
    tokens = {
        production.atom_value
        for production in spec.productions
        if production.atom_value is not None
        and production.atom_value not in delimiters
        and any(delimiter in production.atom_value for delimiter in delimiters)
    }
    return tuple(sorted(tokens))


def _glued_to_a_slot(template: str, labels: Iterable[str]) -> str | None:
    # The first slot label in `template` that shares a whitespace-delimited token
    # with anything else, or None. `( a -> b )` keeps every token apart;
    # `(a -> b)` glues the slot `a` to the opening paren.
    #
    # Compared token-wise rather than by scanning for the label, so a label that
    # merely *occurs inside* a literal is not mistaken for a slot - `A` sits
    # inside the quantifier `A.` throughout set.mm, which is the collision
    # `metamath.importer._uncollide` exists for.
    tokens = template.split()

    for label in labels:
        if any(label in token and token != label for token in tokens):
            return label

    return None


def _check_token_separation(spec: SystemSpec) -> None:
    # A system declaring `token_separated` is held to it, so that the declaration
    # means something and a system meaning to be token-separated is told where it
    # is not. Nothing depends on the answer - see `SystemSpec.token_separated` -
    # so this refuses a *mis-declaration*, never a system that simply did not
    # declare.
    #
    # Production templates only. They are what a formula is read against; a line
    # shape carries its own field syntax (`<wff> [<reference>]`), and definitions
    # and rule schemas never receive `bracket_opaque` at all.
    if not spec.token_separated:
        return

    for prod in spec.productions:
        if not prod.template:
            continue

        glued = _glued_to_a_slot(prod.template, (label for label, _ in prod.bindings))

        if glued is not None:
            raise DeclarativeError(
                f"Production {prod.name!r} declares token_separated but writes "
                f"{glued!r} against another token in {prod.template!r}. Separate every "
                f"token with a space, or declare token_separated=False."
            )


def _binding_patterns(bindings: list[tuple[str, str]], ctx: FormalSystemContext) -> dict[str, Pattern]:
    # Map a `with`-style binding list `[(var, sort)]` to `{var: sort_pattern}`,
    # the string-variable dict the engine's pattern/rule builders consume.
    return {var: ctx.variables[sort] for var, sort in bindings}


def _binding_scopes(prod: Production, pattern: StringPattern) -> dict[str, tuple[str, ...]]:
    """Validate ``prod.scopes_over`` against the template and return it in the
    projected form (``{slot: (slot, ...)}``).

    A binding slot is a claim about *this* production's slots, so everything it
    can get wrong is decidable here: both sides must name slots the template
    actually has, and nothing scopes over itself. Checked at build rather than
    trusted, because the whole point of the declaration is that a later stage
    (a definition's inferred ``fresh`` clause) reads it as fact.
    """
    # The pattern's variables are exactly the declared bindings that occur in the
    # template — one that does not occupies no slot, so there is no position for
    # it to bind at and no child for it to scope over.
    slots = set(pattern.variables)

    def require_slot(var: str, role: str) -> None:
        if var not in slots:
            raise DeclarativeError(
                f"Production {prod.name!r} declares that {role} names a slot "
                f"{var!r}, but its template '{prod.template}' has no such slot. "
                f"A binding slot may only name this production's own slots "
                f"({', '.join(sorted(slots)) or 'none'})."
            )

    scopes: dict[str, tuple[str, ...]] = {}
    for binder, scoped in prod.scopes_over.items():
        require_slot(binder, "a binder")
        if not scoped:
            # A slot that binds over nothing is not a binder — a binding that
            # reaches into no slot is no binding. Dropped rather than stored as an
            # empty entry, because presence in this mapping is what marks a slot
            # as binding, and storage records the scopes rather than the keys, so
            # an empty entry would not survive a round trip anyway.
            continue
        for target in scoped:
            require_slot(target, f"the scope of binder {binder!r}")
            if target == binder:
                raise DeclarativeError(
                    f"Production {prod.name!r} declares that slot {binder!r} "
                    f"scopes over itself. A binder scopes over the slots its "
                    f"binding reaches into, which never includes its own."
                )
        scopes[binder] = tuple(scoped)
    return scopes


def _bindable_sorts(
    spec: SystemSpec, ctx: FormalSystemContext
) -> dict[Constructor, tuple[str, str, str]]:
    """Every production a binder can bind, mapped to the binder that can bind it
    — ``(binding production, binder slot, the sort that slot ranges over)``.

    A binder slot names the sort it ranges over, and a sort admits its own
    branches — so ``∀x.phi`` declaring ``x : setvar`` says that *everything
    `setvar` admits* is bindable, including the atoms enumerating it. That is the
    whole of the deduction; ``Constructor.admits`` already computes the closure.

    Keyed by constructor rather than name because it is the constructor a
    production is compared by, and two productions may spell the same token.
    Where several binders reach one production the first in spec order is kept,
    which only decides which binder the error names — ``admits`` is a frozenset,
    so nothing may depend on *its* order.
    """
    bindable: dict[Constructor, tuple[str, str, str]] = {}
    for prod in spec.productions:
        constructor = constructor_for(ctx.variables[prod.name])
        # The projected `scopes_over`, not the spec's: it is the validated and
        # normalised one (`_binding_scopes` drops a slot that scopes over nothing,
        # which declares no binding at all).
        for binder in constructor.scopes_over:
            sort = constructor.slot_sorts[binder]
            for admitted in sort.admits:
                bindable.setdefault(admitted, (prod.name, binder, sort.name))
    return bindable


def _validate_constant_declarations(spec: SystemSpec, ctx: FormalSystemContext) -> None:
    """Refuse a ``denotes_constant`` declaration the grammar contradicts.

    ``denotes_constant`` is trusted — nothing about a production's shape settles
    it, so the author declares it (see :class:`Production`). Binding slots make
    exactly one class of mistake checkable: a production in the sort a binder
    ranges over yields tokens that binder can *bind*, and a token that can be
    bound is not a constant of the object language whatever the author ticked.

    This is the hole ``test_an_atom_constant_in_the_variable_sort_is_not_excused``
    documents. ``setvar ::= [A-Z] | c`` with ``c`` declared constant admits
    ``T ≝ (c ∈ c)``, and ``∀c.T ⟶ ∀c.(c ∈ c)`` then captures ``c`` — the one
    direction of the declaration that costs soundness. Refused here, naming the
    binder that settles it.

    It narrows the trusted surface rather than removing it: a sort no binder
    mentions is still the author's call, and a grammar that declares no binding
    slots is checked exactly as much as it was before — which is not at all.
    """
    bindable = _bindable_sorts(spec, ctx)
    for prod in spec.productions:
        if not prod.denotes_constant:
            continue
        binder = bindable.get(constructor_for(ctx.variables[prod.name]))
        if binder is None:
            continue
        binder_production, binder_slot, binder_sort = binder
        # A sort admits its branches transitively, so the production's own sort
        # need not be the one the binder names — say both when they differ.
        reached = (
            "" if binder_sort == prod.sort else f", and {binder_sort!r} admits {prod.sort!r}"
        )
        raise DeclarativeError(
            f"Production {prod.name!r} (sort {prod.sort!r}) is declared to denote "
            f"a constant of the object language, but production "
            f"{binder_production!r} binds {binder_sort!r} through its slot "
            f"{binder_slot!r}{reached}. A token a binder can bind is a variable of "
            f"the object language, not a constant: declaring it one would let a "
            f"definition introduce it, and an unfold under that binder would "
            f"capture it. Drop the declaration; or, if it really names one fixed "
            f"thing, move it out of the sort the binder ranges over."
        )


def build_system(spec: SystemSpec) -> FormalSystem:
    """Build a :class:`FormalSystem` directly from a :class:`SystemSpec`.

    Raises :class:`DeclarativeError` for a structurally-invalid spec (e.g. a line
    shape with no grammar-sort placeholder); :func:`build_spec` wraps that into
    the ``{"errors": [...]}`` contract.
    """
    # A string-rewriting rule is justified by associative matching over surface
    # strings, with no term binding to evaluate side-conditions against; refuse
    # the pairing rather than silently ignoring a proviso the author wrote.
    for rule in spec.rules:
        if rule.matching == "string" and rule.side_conditions:
            raise DeclarativeError(
                f"Rule {rule.label!r} uses string matching, which cannot enforce "
                f"side-conditions; drop them or switch it to structural matching."
            )
        # A discharge rule is checked by consuming its subproof (check_discharge);
        # that path never evaluates line antecedents or side-conditions, so
        # configuring them would silently drop a soundness constraint. Refuse the
        # pairing rather than accept a rule whose provisos are ignored.
        if rule.subproof is not None and (rule.antecedents or rule.side_conditions):
            raise DeclarativeError(
                f"Rule {rule.label!r} discharges a subproof, so it cannot also carry "
                f"antecedents or side-conditions (the discharge check ignores them); "
                f"remove them."
            )

    name = _identifier(spec.name) or "System"
    ctx = FormalSystemContext()
    system = FormalSystem(name=name)
    ctx.variables[name] = system

    brackets = _bracket_map(spec)
    opaque = _bracket_opaque_tokens(spec, brackets)
    _check_token_separation(spec)

    def register(pattern: Pattern) -> Pattern:
        # Every named pattern respects the system's brackets (parity with the
        # old post-compile `_patch_brackets`, which walked the same set), and
        # steps over any declared constant that merely spells one.
        pattern.respect_brackets = brackets
        pattern.bracket_opaque = opaque
        return pattern

    def unregistered(pattern: Pattern) -> Pattern:
        # Bracket parity deliberately not applied — see its uses.
        return pattern

    def declare(pattern: Pattern, prod: Production) -> Pattern:
        # Carry the author's object-language role onto the built pattern. Only a
        # *leaf* production can ever be the term this decides about, but setting
        # it uniformly keeps one path and costs nothing.
        pattern.denotes_constant = prod.denotes_constant
        # A binder is a *slot* of a template, so an atomic production has nowhere
        # to put one. Refused rather than ignored: silently dropping it would
        # leave a definition's `fresh` clause inferred from a grammar the author
        # thinks says something it does not (see `_binding_scopes`).
        if prod.template is None and prod.scopes_over:
            raise DeclarativeError(
                f"Production {prod.name!r} declares binding slots "
                f"({', '.join(sorted(prod.scopes_over))}), but it is atomic and has "
                f"no template, so it has no slots. Binding slots belong on the "
                f"production whose notation does the binding."
            )
        return pattern

    # 1. Atomic productions: regex leaves, atom constants, and atom families.
    for prod in spec.productions:
        if prod.regex is not None:
            ctx.variables[prod.name] = declare(
                register(RegexPattern(name=prod.name, pattern=_anchor(prod.regex))), prod
            )
        elif prod.atom_value is not None or prod.atom_base is not None:
            # An indexed family is a *supply* of interchangeable tokens — the
            # whole point of `AtomPattern.fresh` is that there is always a next
            # one, which is what eigenvariable selection draws on. So no grammar
            # can make one denote a single fixed thing, and unlike a one-token
            # atom (a constant in `formula ::= ⊥`, a variable in
            # `setvar ::= a | b | c`) this is not a judgement call the author
            # could get right. Refuse it rather than let a declaration excuse a
            # leaf a binder can bind.
            if prod.atom_base is not None and prod.denotes_constant:
                raise DeclarativeError(
                    f"Production {prod.name!r} is an indexed atom family "
                    f"('{prod.atom_base}_#'), so it cannot denote a constant of the "
                    f"object language: every member is an interchangeable "
                    f"placeholder a binder may bind, and fresh ones can always be "
                    f"minted. Declare a specific token with `atom_value` if you "
                    f"meant a constant."
                )
            # An atom constant (`value`, one literal token) or indexed family
            # (`base`, the infinite `p_#` -> p_0, p_1, ...). A single token needs
            # no bracket parity, so it is not `register`ed — its `respect_brackets`
            # stays None.
            ctx.variables[prod.name] = declare(
                AtomPattern(
                    name=prod.name,
                    value=prod.atom_value,
                    base=prod.atom_base,
                ),
                prod,
            )
    # (Inline line parts are registered per-line in step 5, immediately before
    # the line that uses them, so two lines may reuse a part name with different
    # regexes without the shared namespace binding both to the last one.)

    # 2. Forward-declare every sort as an empty union (order independence).
    for sort in spec.sort_names():
        ctx.variables[sort] = register(
            UnionPattern(name=sort, patterns=[])
        )

    # 3. Composite productions.
    for prod in spec.productions:
        if prod.template is None:
            continue
        pattern = StringPattern(name=prod.name, pattern=prod.template)
        pattern.add_variables(_binding_patterns(prod.bindings, ctx))
        pattern.scopes_over = _binding_scopes(prod, pattern)
        # A nullary template (`S`, `∅`) parses to a ground leaf, so it too can be
        # the leaf a definition introduces and carries the declaration.
        ctx.variables[prod.name] = declare(register(pattern), prod)

    # 4. Fill each sort union with its members, in declared order.
    for sort in spec.sort_names():
        union = ctx.variables[sort]
        for prod in spec.productions:
            if prod.sort == sort:
                union.add_pattern(ctx.variables[prod.name])

    # 4a. Project the grammar to its kernel constructors, now that the unions are
    # complete. Everything from here on builds terms, and a term's sort is a
    # constructor: a union projected while still empty would be linked with no
    # branches and would admit nothing but itself thereafter. Done explicitly so
    # the moment is chosen, rather than falling out of whichever term is built
    # first (see kernel.constructors.project_grammar).
    # `ctx.variables` is the whole build namespace, which also holds referenced
    # systems; only the productions are projectable.
    project_grammar(p for p in ctx.variables.values() if isinstance(p, Pattern))

    # 4b. Now that every sort knows what it admits, cross-check the one class of
    # `denotes_constant` mistake the grammar can actually settle: a token a binder
    # ranges over is not a constant of the object language.
    _validate_constant_declarations(spec, ctx)

    # 5. Lines: a statement pattern + logical line type per declared line. Each
    # line's inline parts are registered just before it is built (see step 1).
    if spec.lines:
        sorts = set(spec.sort_names())
        for line in spec.lines:
            # Commentary is prose, not a term: bracket parity must not apply to
            # it, or an unbalanced bracket in a note ("-- discharge ( here")
            # stops the line matching at all and fails the proof. Same reason an
            # atom constant is left unregistered in step 1.
            line_register = unregistered if line.behaviour == "comment" else register
            for part in line.parts:
                built = line_register(
                    RegexPattern(name=part.name, pattern=_anchor(part.regex))
                )
                # Two lines may declare the same part name with *different*
                # regexes, and each must keep its own — that is what the rebind
                # is for. Declaring the identical part twice is not that case,
                # and must not mint a second object: productions are canonical
                # (one object per production, so sort identity decides sort
                # equality — see kernel.constructors.Constructor.admits), and two
                # equivalent-but-distinct patterns would break it.
                previous = ctx.variables.get(part.name)
                if (
                    isinstance(previous, RegexPattern)
                    and previous.pattern == built.pattern
                    and previous.respect_brackets == built.respect_brackets
                ):
                    built = previous
                ctx.variables[part.name] = built
            _build_line(line, sorts, ctx, system, line_register)

    # 6. Axioms -> axiom-behaviour line types.
    for ax in spec.axioms:
        _build_axiom(ax, ctx, system, register)

    # 7. Rules -> inference rules.
    for rule in spec.rules:
        system.add_inference_rule(_build_rule(rule, ctx))

    # 8. Publish the build variables into the proof context, then finalise
    # definitions against that (now complete) context, so `add_notation` can
    # match the lower form against the productions.
    system.context.variables.update(ctx.variables)
    # Wired here rather than at the end because a definition's justification reads
    # a statement in the system's own grammar, which needs the build context. The
    # grammar is complete as of the line above; only the pattern dictionary (built
    # last) still is not, and nothing on this path consults it.
    system.build_context = ctx
    # Per position, whether the definition layered — kept in spec order so a
    # caller can map it back to a specific definition even when two share a
    # defined form (see registered_definition_layering). A cited definition name
    # must be unambiguous, so a duplicate label is rejected here rather than
    # silently letting `[<name>, <line>]` pick one.
    seen_labels: set[str] = set()
    layering: list[bool] = []
    for defn in spec.definitions:
        if defn.label is not None:
            if defn.label in seen_labels:
                raise DeclarativeError(f"Duplicate definition label '{defn.label}'.")
            seen_labels.add(defn.label)
        layering.append(_finalise_definition(defn, ctx, system))
    system.definition_layering = layering

    # 9. Parse each rule's provisos now that definitions have resolved, so a
    # proviso's term argument may use defined notation (e.g. `equal(t, ∅)`). Each
    # rule brings its own metavariables.
    for inference_rule in system.inference_rules:
        if not inference_rule.pending_side_conditions:
            continue
        rule_context = copy(system.context)
        rule_context.string_variables = {
            **rule_context.string_variables, **(inference_rule.variables or {})
        }
        inference_rule.side_conditions.extend(
            parse_side_condition(line, rule_context)
            for line in inference_rule.pending_side_conditions
        )
        inference_rule.pending_side_conditions = []

    # 10. Index the patterns (the build context was wired at step 8).
    system.build_pattern_dictionary()
    return system


def _build_line(line: LineSpec, sorts: set[str], ctx: FormalSystemContext,
                system: FormalSystem, register: Callable[[Pattern], Pattern]) -> None:
    if line.scope not in _LINE_SCOPES:
        raise DeclarativeError(
            f"Line {line.name!r} has invalid scope {line.scope!r}; "
            f"expected one of {', '.join(repr(s) for s in _LINE_SCOPES)}."
        )
    if line.behaviour not in _LINE_BEHAVIOURS:
        raise DeclarativeError(
            f"Line {line.name!r} has invalid behaviour {line.behaviour!r}; "
            f"expected one of {', '.join(repr(b) for b in _LINE_BEHAVIOURS)}."
        )
    if line.behaviour == "comment" and line.scope is not None:
        # A subproof has to be opened by a line the discharge rule can cite, and
        # commentary is unnumbered — so the subproof could never be discharged.
        raise DeclarativeError(
            f"Line {line.name!r} is commentary, so it cannot open a "
            f"{line.scope} scope; no rule could discharge it."
        )
    template, placeholders, logical_ph, reference_ph = _line_layout(line, sorts)

    # Each line gets a distinctly-named pattern (a single line named "statement"
    # keeps the historical "statement_pattern" name).
    pattern_name = f"{_identifier(line.name)}_pattern"
    pattern = StringPattern(name=pattern_name, pattern=template)
    pattern.add_variables(_binding_patterns([(var, ph) for ph, var in placeholders], ctx))
    ctx.variables[pattern_name] = register(pattern)

    line_type = LineType(
        name=line.name,
        pattern=pattern,
        behaviour=line.behaviour,
        scope=line.scope,
        # Declared, not merely absent: a comment line has no formula to project,
        # so leaving the field unset keeps prose out of anything that harvests
        # line formulae (the term graph, definitional steps).
        formula_field=logical_ph[1] if logical_ph is not None else None,
        reference_field=reference_ph[1] if reference_ph is not None else None,
    )
    ctx.variables[line.name] = line_type
    system.add_line_type(line_type)


def _build_axiom(axiom: Rule, ctx: FormalSystemContext, system: FormalSystem,
                 register: Callable[[Pattern], Pattern]) -> None:
    pattern_name = f"{_identifier(axiom.name)}_axiom"
    pattern = StringPattern(name=pattern_name, pattern=axiom.deduction)
    pattern.add_variables(_binding_patterns(axiom.bindings, ctx))
    ctx.variables[pattern_name] = register(pattern)

    # A bare axiom asserts its whole match, hence `formula_field="self"`.
    line_type = LineType(
        name=_identifier(axiom.name), pattern=pattern, behaviour="axiom", formula_field="self"
    )
    ctx.variables[_identifier(axiom.name)] = line_type
    system.add_line_type(line_type)


def _build_rule(rule: Rule, ctx: FormalSystemContext) -> InferenceRule:
    # The rule's bindings are its metavariables; put them in a scoped copy of the
    # build context so `build_schema_pattern` treats them as variables — the
    # scope is per-rule, never the system's own.
    string_variables = _binding_patterns(rule.bindings, ctx)
    rule_ctx = copy(ctx)
    rule_ctx.string_variables = dict(string_variables)

    inference_rule = InferenceRule(
        name=_identifier(rule.name),
        label=rule.label,
        variables=dict(string_variables),
        matching=rule.matching,
        subproof_schema=_build_subproof(rule, rule_ctx),
        allow_extra_antecedents=rule.allow_extra_antecedents,
    )
    for antecedent in rule.antecedents:
        inference_rule.antecedents.append(build_schema_pattern(antecedent, rule_ctx, "antecedent"))
    inference_rule.deduction = build_schema_pattern(rule.deduction, rule_ctx, "deduction")
    # Provisos are parsed later (see build_system), once definitions resolve, so a
    # proviso's term argument may use defined notation. Here we only collect them.
    inference_rule.pending_side_conditions = list(rule.side_conditions)
    return inference_rule


def _build_subproof(rule: Rule, rule_ctx: FormalSystemContext) -> SubproofSchema | None:
    # A discharge rule consumes a subproof opened by exactly one of a hypothesis
    # (`assume`) or a fresh variable (`fresh`); its final line must match
    # `derive`. Each is a rule-schema line parsed against the rule's variables,
    # exactly like the deduction.
    subproof = rule.subproof
    if subproof is None:
        return None
    if (subproof.assume is None) == (subproof.fresh is None):
        raise DeclarativeError(
            f"Rule {rule.label!r} subproof must be opened by exactly one of "
            f"'assume' or 'fresh'."
        )
    return SubproofSchema(
        conclusion=build_schema_pattern(subproof.derive, rule_ctx, "subproof"),
        assumption=(build_schema_pattern(subproof.assume, rule_ctx, "subproof")
                    if subproof.assume is not None else None),
        fresh=(build_schema_pattern(subproof.fresh, rule_ctx, "subproof")
               if subproof.fresh is not None else None),
    )


def _justifying_statement(
    justification: Justification, system: FormalSystem, name: str
) -> tuple[Pattern, tuple[SideCondition, ...]] | None:
    # The statement a justification cites, and the provisos it carries, or None if
    # the label names nothing citable. A *proved* theorem is the expected case
    # (Metamath's `sbjust`), but a system's own axiom is equally a settled
    # statement, so a rule with no antecedents serves too.
    theorem = system.promoted_theorems.get(justification.label)
    if theorem is not None:
        return (
            (theorem.deduction, theorem.side_conditions)
            if not theorem.antecedents
            else None
        )
    rule = system.rule_by_label(justification.label)
    if rule is None or rule.antecedents:
        return None
    if rule.is_discharge:
        # A discharge rule cites no lines, so it has no `antecedents` — but it
        # consumes a whole subproof, which is a premise by another name. Without
        # this, conditional proof settles every `(A → B)` there is.
        return None
    if rule.pending_side_conditions:
        # A rule's provisos are parsed only *after* definitions resolve, so that
        # one may use defined notation — which is exactly why a definition cannot
        # read them here. Rather than inherit a proviso list that is still empty,
        # refuse: the citation would silently drop what the rule holds under.
        raise DeclarativeError(
            f"Definition '{name}' is justified by rule '{justification.label}', whose "
            "provisos are parsed after definitions resolve and so cannot be inherited. "
            "Cite a proved theorem, or drop the rule's provisos."
        )
    return rule.deduction, tuple(rule.side_conditions)


def _discharge_justification(
    defn: Definition, system: FormalSystem, condition: SideCondition | None
) -> SideCondition | None:
    """Settle ``defn``'s proof obligation against the theorem it cites, or refuse.

    Returns the condition the definition is registered under: its own, plus the
    cited theorem's provisos restated in the definition's metavariables. The
    definition *inherits* them because the citation only licences an instance the
    theorem itself licences — `sbjust` holds under `$d x y z` and so, therefore,
    does every use of `df-sb` that leans on it. That is stricter than Metamath,
    which re-proves the hypothesis per use; strictness costs a refused unfold, and
    in `set.mm` costs nothing at all, since a definition needing a justification
    carries the same `$d` as its justifying theorem.
    """
    justification = defn.justification
    if justification is None:
        raise DeclarativeError(f"Definition '{defn.name}' has no justification to discharge.")

    cited = _justifying_statement(justification, system, defn.name)
    if cited is None:
        raise DeclarativeError(
            f"Definition '{defn.name}' is justified by '{justification.label}', which is "
            "not a proved theorem or an axiom of this system with no premises of its "
            "own. An obligation is discharged by citing something already settled."
        )
    statement, provisos = cited

    try:
        obligation = promote_from_source(
            system,
            label=f"{defn.name}.justification",
            statement=justification.statement,
            metavariables=dict(defn.bindings),
        )
    except ValueError as exc:
        raise DeclarativeError(
            f"Definition '{defn.name}' states its obligation as "
            f"'{justification.statement}', which the system cannot read: {exc}"
        ) from exc

    # The obligation must be an *instance* of what was proved, so the cited
    # statement is the schema and the obligation the subject: a theorem may be
    # more general than the obligation needs, never less. The obligation's own
    # metavariables stay rigid, which is what makes the discharge hold for every
    # substitution the definition is later used at.
    binding = match(
        statement_term(statement), statement_term(obligation.deduction), system.context
    )
    if binding is None:
        raise DeclarativeError(
            f"Definition '{defn.name}' states its obligation as "
            f"'{justification.statement}', which is not an instance of what "
            f"'{justification.label}' proves."
        )

    try:
        inherited = [restate(proviso, binding, system.context) for proviso in provisos]
    except ValueError as exc:
        raise DeclarativeError(
            f"Definition '{defn.name}' cannot inherit a proviso of "
            f"'{justification.label}': {exc}"
        ) from exc

    if not inherited:
        return condition
    parts = (*( () if condition is None else (condition,) ), *inherited)
    return parts[0] if len(parts) == 1 else And(parts)


def _check_condition_is_checkable(defn: Definition, built: KernelDefinition) -> None:
    # A definition's proviso is checked against the binding an *unfold* produces,
    # and that binding comes from matching the defined form against the redex
    # (`kernel.definitions.unfold`). So a proviso may only name metavariables the
    # defined form supplies: one naming anything else - a parameter of the
    # defining form alone, a variable a `$d` mentions but neither form uses - has
    # nothing to resolve against, and the kernel raises rather than returning a
    # verdict.
    #
    # Unlike a rule, which fails closed on a malformed proviso
    # (`InferenceRule._side_conditions_hold`), `unfold` lets that escape into the
    # proof parse - and a generic `[Def, n]` tries every definition in scope, so
    # one such definition breaks definitional steps system-wide. Settle it here,
    # where the author can act on it, exactly as an unsound defining form is.
    if built.condition is None:
        return
    # The declared binders count as supplied: the unfold resolves each to the leaf
    # it takes there and exposes it under its declared name, so a proviso may
    # constrain one (`kernel.definitions._condition_binding`).
    supplied = set(built.higher.free_vars()) | {binder.name for binder in built.fresh}
    orphaned = sorted(references(built.condition) - supplied)
    if orphaned:
        listed = ", ".join(repr(name) for name in orphaned)
        raise DeclarativeError(
            f"Definition '{defn.name}' has a proviso naming {listed}, which its "
            f"defined form '{defn.higher}' does not supply and its `fresh` clause "
            "does not declare. A proviso is checked against the match between the "
            "defined form and the term being unfolded, plus the binders that unfold "
            f"resolves, so it can constrain nothing else. Either make {listed} a "
            "parameter of the defined form, or state the proviso over what it has."
        )


def _finalise_definition(defn: Definition, ctx: FormalSystemContext, system: FormalSystem) -> bool:
    """Register ``defn`` against the now-complete grammar, returning whether it
    layered — ``True`` when its defining (lower) form was recognised (given the
    definitions already in context), ``False`` when it matched nothing and so was
    dropped. A recognised form is added to the proof context."""
    union = ctx.variables[defn.sort]
    context_copy = copy(system.context)
    context_copy.string_variables.update(_binding_patterns(defn.bindings, ctx))

    # The defining form's bound variables, resolved to their sort patterns, so the
    # term checker treats them as binders (capture-avoiding unfold) rather than as
    # stray ground leaves that would force the string path.
    fresh_patterns = _binding_patterns(defn.fresh, ctx)

    # A `;` inside a `where` proviso conjoins several kernel conditions.
    #
    # Parsed with the binders in scope as well as the parameters, so a proviso may
    # name one. A binder is stored abstractly and has no fixed name to constrain,
    # so `disjoint(z, x)` on a definition whose `fresh` clause names `z` means
    # "whatever this binder is called at this unfold" — which is what an author
    # writing it means, and what `kernel.definitions._condition_binding` resolves
    # it to. Without the binders here `z` parses as the literal token `z`, which is
    # a coherent reading of nothing anybody wanted.
    where_strings = (
        [part.strip() for part in defn.condition.split(";") if part.strip()]
        if defn.condition
        else []
    )
    proviso_context = copy(context_copy)
    proviso_context.string_variables = {**fresh_patterns, **context_copy.string_variables}
    kernel_condition = combine_side_conditions(where_strings, proviso_context)

    # A definition holding only under an obligation discharges it here, before any
    # of it is registered — the obligation is stated in the grammar the definition
    # extends, so it must be settled while that grammar is still the one in force.
    if defn.justification is not None:
        kernel_condition = _discharge_justification(defn, system, kernel_condition)

    # Whether the defining form is recognised *given the definitions before it* is
    # what "layering" means, and it is settled before anything is registered: a
    # definition that does not layer must leave the grammar untouched.
    if union.match(defn.lower, context_copy) is None:
        return False

    notation = union.add_notation(defn.higher, context_copy)
    # Whether the notation was already in scope, so a failure below knows whether
    # removing it is undoing *this* registration or confiscating an earlier
    # definition's grammar — two definitions may share one defined form, and
    # `add_notation` hands back the production the first one registered.
    shared_with_an_earlier_definition = notation in system.context.definitions
    system.context.definitions.add(notation)

    try:
        return _register_notated_definition(
            defn, union, notation, kernel_condition, fresh_patterns, system
        )
    except DeclarativeError:
        # Every refusal past this point is a *late* one: the notation is already
        # in scope, so the defined form parses as defined notation while no kernel
        # definition backs it. Harmless when a whole build is being discarded, but
        # `register_definition` mutates a live system, and a caller that catches
        # this to keep the assertion as an axiom (which is what a corpus import
        # does) would be left with the grammar half-extended.
        if not shared_with_an_earlier_definition:
            system.context.definitions.discard(notation)
        raise


def _register_notated_definition(
    defn: Definition,
    union: Pattern,
    notation: DefinedNotation,
    kernel_condition: SideCondition | None,
    fresh_patterns: dict[str, Pattern],
    system: FormalSystem,
) -> bool:
    # The half of `_finalise_definition` that runs with the defined form's notation
    # already in scope — which is what makes that form grammatical, and so what
    # every check below needs. Split out so a refusal here can withdraw it again.

    # Whether the sort actually parses the defined form through *this* notation.
    # A sort tries its own productions before its notations, so a form the grammar
    # already spells (`Define x ∈ y as ...`) parses to a declared production and
    # never reaches here. Asked of the registered notation rather than of the
    # grammar-before-it, because two definitions may share one defined form: the
    # second finds the first's notation, which is the same production and still
    # its own leaf.
    matched = union.match(defn.higher, system.context)
    parses_to_its_own_leaf = matched is not None and matched.pattern is notation.template

    # A nullary defined form is a new ground leaf of the grammar that no production
    # declared a role for, so the build settles its role here: the leaf abbreviates
    # one fixed term, and a *later* definition may introduce it exactly as it may a
    # declared constant (`T ≝ S` layers on `S ≝ ⊥`).
    #
    # Settled *before* the kernel definition is built, not after, because building
    # it projects this template to a constructor and a constructor snapshots the
    # declaration. Safe in both directions: the definition's own leaf is always
    # among its defined form's, so `introduced_leaves` never puts it to the
    # constants check during this build, and a definition that goes on to fail
    # withdraws the notation this is written on (see the caller).
    notation.template.denotes_constant = denotes_a_constant(notation, parses_to_its_own_leaf)

    # Build the kernel counterpart now, against the context the notation has just
    # entered — a definition's *defined* form is grammatical only because its
    # notation is registered, so this must follow the add. `system.context` is
    # deliberately the one used (not `context_copy`): it is what a proof is
    # checked in, and the definition's own binding metavariables in `context_copy`
    # would parse the parameters differently.
    #
    # A definition with no sound kernel reading is rejected here rather than
    # silently accepted and refused per-step later.
    try:
        kernel_definition = build_kernel_definition(
            notation,
            defn.lower,
            system.context,
            condition=kernel_condition,
            fresh=fresh_patterns or None,
            label=defn.label,
        )
    except DefinitionError as exc:
        raise DeclarativeError(str(exc)) from exc

    _check_condition_is_checkable(defn, kernel_definition)
    system.add_definition(kernel_definition)

    # A freshly added definition or one that de-duplicated into an existing
    # equivalent — either way its form was recognised, so the definition layers.
    return True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def register_definition(defn: Definition, system: FormalSystem) -> bool:
    """Register one definition against an already-built ``system``.

    The same registration :func:`build_system` performs for every definition in a
    spec, for a caller that has one to add later — an import walking a corpus, in
    which the theorem a definition's justification cites is promoted as the walk
    reaches it and so is not there when the system is built.

    Returns whether the definition *layered* (see :func:`_finalise_definition`),
    appending that to ``system.definition_layering`` so it stays positional with
    ``system.definitions`` however the definitions arrived, and raises
    :class:`DeclarativeError` if the definition cannot be registered soundly.
    """
    if system.build_context is None:
        raise DeclarativeError(
            f"Cannot register definition '{defn.name}' against a system with no "
            "build context."
        )
    # A cited definition name must resolve to one definition, and nothing else
    # enforces that: `_definition_by_label` takes the first match, so a collision
    # would leave the second silently uncitable. `build_system` refuses a
    # duplicate within its own spec; this is the same refusal against whatever the
    # system already carries.
    if defn.label is not None and any(d.label == defn.label for d in system.definitions):
        raise DeclarativeError(f"Duplicate definition label '{defn.label}'.")
    layered = _finalise_definition(defn, system.build_context, system)
    system.definition_layering.append(layered)
    return layered


def build_spec(spec: SystemSpec, system_dict: dict | None = None) -> dict:
    """Build a ``FormalSystem`` from a :class:`SystemSpec`.

    The entry point for callers that hold a ``SystemSpec`` -- e.g. a persistence
    layer that reconstructs one from database rows, or a test that assembles one
    directly. Returns ``{"system": FormalSystem}`` on success or
    ``{"errors": [...]}`` when the spec is invalid.

    ``system_dict`` is reserved for cross-system references (a parent system a
    child inherits from). The declarative path does not resolve inheritance yet,
    so it is currently unused; it is kept on the signature so callers of the
    engine's public build entry point don't break when that lands.
    """
    try:
        return {"system": build_system(spec)}
    except DeclarativeError as exc:
        return {"errors": [str(exc)]}
    except Exception as exc:  # noqa: BLE001
        # A spec that reaches here passed storage validation but the engine still
        # rejected it (e.g. a malformed proviso). Preserve the build contract --
        # return errors rather than raising into the caller (a 500 at the API).
        return {"errors": [str(exc)]}


def registered_definition_layering(spec: SystemSpec) -> list[bool]:
    """Per definition, in ``spec.definitions`` order, whether it *layers*.

    Definitions layer positionally: a definition may build on the ones before it,
    so its defining (lower) form is parsed against the grammar those earlier
    definitions have already extended. A definition placed **ahead** of one whose
    notation its lower form uses does not raise -- its lower form simply matches
    nothing, and it is dropped silently. The returned flag is ``True`` for a
    definition that was recognised, ``False`` for one that was dropped.

    Keyed by **position**, not by defined form, so a caller can tell whether a
    *specific* definition would be dropped even when two definitions share a
    higher form (a set of forms would collapse them) or are structurally
    equivalent up to renaming (which ``add_notation`` de-duplicates).

    Layering depends only on the grammar (productions, in their sort unions) and
    the definitions themselves; axioms, rules and lines contribute nothing to it.
    So the build is done against a spec **reduced** to grammar plus definitions:
    an unrelated draft error the draft-tolerant CRUD persisted (a half-written
    rule, a malformed proviso) then can't fail the build and blind the check into
    reporting every definition dropped. Only a broken *grammar* still errors —
    and there no definition can layer at all, so all-``False`` is the honest
    answer (nothing is live for a reorder to drop).

    A definition's *justification* goes with the rules, and for the same reason:
    it cites one, so keeping it would fail the reduced build over something that
    decides nothing about layering — reporting every definition dropped, which is
    exactly what the reduction exists to prevent.
    """
    reduced = copy(spec)
    reduced.axioms = []
    reduced.rules = []
    reduced.lines = []
    reduced.definitions = [
        replace(defn, justification=None) if defn.justification is not None else defn
        for defn in spec.definitions
    ]
    result = build_spec(reduced)
    if "errors" in result:
        return [False] * len(spec.definitions)
    return result["system"].definition_layering


def _uses_parens(spec: SystemSpec) -> bool:
    texts = [p.template or "" for p in spec.productions]
    texts += [d.lower for d in spec.definitions]
    texts += [r.deduction for r in spec.axioms + spec.rules]
    return any("(" in t for t in texts)
