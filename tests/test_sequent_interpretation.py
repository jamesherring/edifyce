"""A Hilbert theorem cited inside a sequent proof, wrapped as ``Γ ⊢ φ``.

S2 of docs/system-relationships-roadmap.md, and the mechanism §6.3 asks for: an
**interpretation** edge whose statement template restates a transferred theorem
in the shape the target proves things in. The two systems here
(`tests/sequent_system.py`) share their whole formula language on purpose, so
the edge renames nothing and the only difference between them is what a
*judgement* is — which is the difference this phase is about, and the one R4b's
rename cannot express.

What the wrap is, asserted rather than described: the transferred theorem's term
gets the target's `turnstile` constructor at its root and the source's own term,
the same object, as a subterm (`test_the_wrap_is_a_term_construction`). Nothing
is rendered and re-parsed, because the target's grammar is entitled to read a
concatenation differently from how the source's read the part.

And the finding, which is the phase's real content:
`test_generalisation_cannot_be_discharged_uniformly_in_the_context` — the wrap
of `ax-gen` is not derivable here for *arbitrary* Γ, so a Hilbert system with
generalisation cannot discharge its obligations onto this one, and the edge that
matters is the propositional fragment's. §9.24 records what that settles.
"""

from __future__ import annotations

import uuid
from copy import copy

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi_users")
pytest.importorskip("aiosqlite")
pytest.importorskip("regex")

from fastapi.testclient import TestClient
from sqlalchemy import NullPool, create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

import app.auth.backend as backend
from app.db import FormalSystem, effective_library
from app.db.promoted_theorems_mapping import load_theorems
from app.db.session import get_session
from app.main import app
from website.logical.declarative import build_spec
from website.logical.kernel.terms import Node
from website.logical.promotion import TheoremSpec
from website.logical.wrapping import StatementTemplate, build_template, template_errors

from tests.database import async_url, create_tables, database_url, enable_foreign_keys
from tests.sequent_system import hilbert_spec, sequent_spec
from tests.test_cross_system_citation import _chain, promote_into, verify_proof
from tests.test_proofs_api import _TABLES
from tests.test_system_inheritance import seed
from tests.test_system_relations import relate
from tests.test_systems_api import _register_login


@pytest.fixture
def db(tmp_path):
    db_path = database_url(tmp_path, "sequent-interpretation")
    create_tables(db_path, _TABLES)

    async_engine = create_async_engine(async_url(db_path), poolclass=NullPool)
    enable_foreign_keys(async_engine.sync_engine)
    sessionmaker = async_sessionmaker(async_engine, expire_on_commit=False)

    async def override_get_session():
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    yield db_path
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(backend.cookie_transport, "cookie_secure", False)
    with TestClient(app) as test_client:
        yield test_client

# The wrap S2 is about: a Hilbert formula becomes a sequent with an arbitrary
# antecedent. One hole, naming the sort the transferred statement is read at
# here, and one extra — the metavariable the source theorem never had.
WRAP = "G ⊢ {wff}"
EXTRAS = {"G": "context"}

# What an interpretation onto the sequent calculus owes, and what pays it. Each
# is discharged by a *primitive of the target*: the propositional axioms are
# derivable from `id`, `WL` and `→R`, and modus ponens from `→L` and `cut` —
# see `test_each_obligation_is_discharged_by_an_actual_sequent_proof`, which
# writes those derivations out rather than asserting them.
OBLIGATIONS = [("ax-1", "→R"), ("ax-2", "→R"), ("ax-3", "→R"), ("MP", "cut")]


def two_systems(db_path, client, email: str, *, generalisation: bool = False):
    """A published Hilbert system and a published sequent one, unrelated."""
    owner = _register_login(client, email)
    source = seed(
        db_path, hilbert_spec(generalisation=generalisation), owner, None
    )
    target = seed(db_path, sequent_spec(), owner, None)
    return source, target


def interpret(db_path, source: str, target: str, **overrides) -> str:
    """The S2 edge: no rename, a wrap, and the four obligations."""
    settings = {
        "kind": "interpretation",
        "obligations": OBLIGATIONS,
        "template": WRAP,
        "extras": EXTRAS,
    }
    settings.update(overrides)
    return relate(db_path, source, target, **settings)


# The theorem that crosses. `(P → P)` is the smallest Hilbert theorem worth
# having and the one every test below cites; it is *imported* rather than proved,
# which is what a corpus contributes and what R3's promotion writes.
IDENTITY_LAW = TheoremSpec(
    label="id-law", statement="(P → P)", metavariables={"P": "wff"}
)


# ---------------------------------------------------------------------------
# The template, before any of it reaches a database
# ---------------------------------------------------------------------------


def test_the_wrap_is_a_term_construction() -> None:
    # §6.3's requirement, asserted structurally rather than on the rendered
    # string: the wrapped statement has the *target's* constructor at its root
    # and the source's own term as a subterm — the same object, not an equal one.
    #
    # That is what says nothing was rendered and re-parsed. A re-parse would give
    # an equal term when the two grammars agree and a different one when they do
    # not, and the whole reason an edge exists is that they need not agree.
    target = build_spec(sequent_spec())["system"]
    built = build_template(target, StatementTemplate(WRAP, EXTRAS))
    assert built is not None

    source = build_spec(hilbert_spec())["system"]
    statement = _statement_term(source, "(P → P)", {"P": "wff"})

    wrapped = built.wrap(statement)
    assert isinstance(wrapped, Node)
    assert wrapped.constructor.name == "turnstile"
    assert wrapped.children["p"] is statement
    assert wrapped.children["g"].name == "G"
    assert wrapped.to_string() == "G ⊢ (P → P)"


def test_a_template_that_does_not_compose_is_refused_with_a_reason():
    # Each way a template fails to become a statement of the target, and the
    # message that says which. `build_template` answers the resolver's question
    # (a boolean, failing closed); this is the author's, and the two are split
    # for the same reason `translation_errors` and `_translates` are (§9.17).
    target = build_spec(sequent_spec())["system"]

    assert "no hole" in " ".join(
        template_errors(target, StatementTemplate("G ⊢ P", EXTRAS))
    )
    assert "2 holes" in " ".join(
        template_errors(target, StatementTemplate("{wff} ⊢ {wff}", EXTRAS))
    )
    assert "does not declare" in " ".join(
        template_errors(target, StatementTemplate("G ⊢ {formula}", EXTRAS))
    )
    assert "does not declare" in " ".join(
        template_errors(target, StatementTemplate(WRAP, {"G": "sequence"}))
    )
    # Parses at *some* sort but not at one a proof line is read at: `G , {wff}`
    # is a perfectly good `context`, and a line of this system is a `sequent`.
    assert "does not parse at any" in " ".join(
        template_errors(target, StatementTemplate("G , {wff}", EXTRAS))
    )
    # And the one that must be accepted, so the refusals above are not a
    # function that refuses everything.
    assert template_errors(target, StatementTemplate(WRAP, EXTRAS)) == []


# ---------------------------------------------------------------------------
# The edge, end to end
# ---------------------------------------------------------------------------


def test_a_hilbert_theorem_is_citable_wrapped_in_a_sequent_proof(db, client):
    # The headline, and the pair that carries it. `∅ ⊢ (P → P)` cites a theorem
    # this system never proved and whose statement is not even a sentence of it —
    # `(P → P)` is a `wff`, and a line here is a `sequent`. The edge is what
    # makes the wrapped form citable, and the same proof fails without it.
    source, target = two_systems(db, client, "wrap@example.com")
    promote_into(db, source, IDENTITY_LAW)

    assert verify_proof(client, db, target, "∅ ⊢ (P → P) [id-law]")["success"] is False

    interpret(db, source, target)
    assert verify_proof(client, db, target, "∅ ⊢ (P → P) [id-law]")["success"] is True


def test_the_context_is_instantiated_by_the_citing_line(db, client):
    # The extra is a *metavariable*, not a fixed empty context: the same
    # transferred theorem justifies the wrapped form at whatever antecedent the
    # line happens to have, including a two-assumption one. That is what makes
    # the wrap worth having rather than a way to import closed theorems.
    source, target = two_systems(db, client, "context@example.com")
    promote_into(db, source, IDENTITY_LAW)
    interpret(db, source, target)

    for context in ("∅", "A", "∅ , A , B", "a = a"):
        assert verify_proof(
            client, db, target, f"{context} ⊢ (P → P) [id-law]"
        )["success"] is True, context


def test_the_transferred_theorem_is_still_schematic_in_its_own_metavariables(db, client):
    # `P` is the source theorem's own metavariable and travels with it, so the
    # wrapped entry is schematic in both — the context *and* the formula. The
    # rejected half is what says the schema is still a schema and not the text:
    # `(P → Q)` is not an instance of `(P → P)` at any Γ.
    source, target = two_systems(db, client, "schematic@example.com")
    promote_into(db, source, IDENTITY_LAW)
    interpret(db, source, target)

    assert verify_proof(
        client, db, target, "∅ ⊢ (¬A → ¬A) [id-law]"
    )["success"] is True
    assert verify_proof(
        client, db, target, "∅ ⊢ (A → B) [id-law]"
    )["success"] is False


def test_an_edge_with_no_template_transfers_nothing_citable_here(db, client):
    # The pair that says the *template* is what does the work rather than the
    # edge. Without it a `wff` arrives as a `wff`, and no line of this system is
    # one — so the citation resolves to a theorem that cannot apply to any
    # sequent, which is exactly what an unwrapped interpretation should do.
    source, target = two_systems(db, client, "no-template@example.com")
    promote_into(db, source, IDENTITY_LAW)
    interpret(db, source, target, template=None, extras=None)

    assert verify_proof(client, db, target, "∅ ⊢ (P → P) [id-law]")["success"] is False


def test_a_template_the_target_cannot_compose_transfers_nothing(db, client):
    # The fourth way an edge resolves nothing, beside `draft`, an outstanding
    # obligation, and a rename that does not check out — and it fails the same
    # way they do: silently, as a citation that does not resolve. The author's
    # version of this refusal is the route's (`template_errors`); the resolver
    # only needs the boolean.
    source, target = two_systems(db, client, "bad-template@example.com")
    promote_into(db, source, IDENTITY_LAW)
    interpret(db, source, target, template="G ⊢ {formula}")

    assert verify_proof(client, db, target, "∅ ⊢ (P → P) [id-law]")["success"] is False


def test_an_outstanding_obligation_still_stops_a_wrapped_transfer(db, client):
    # §2's gate is unchanged by the wrap, and the roadmap asks for this as a
    # *pair* so that the test shows the obligation carrying the weight rather
    # than something else about the setup. One line differs between the two
    # calls: whether `MP` has a discharge.
    source, target = two_systems(db, client, "withdrawn@example.com")
    promote_into(db, source, IDENTITY_LAW)
    interpret(db, source, target, obligations=[*OBLIGATIONS[:3], ("MP", None)])

    assert verify_proof(client, db, target, "∅ ⊢ (P → P) [id-law]")["success"] is False


# ---------------------------------------------------------------------------
# What the obligations are actually claiming
# ---------------------------------------------------------------------------


def test_each_obligation_is_discharged_by_an_actual_sequent_proof(db, client):
    # The roadmap asks for the discharges to be real derivations rather than
    # labels, and this is them. Each is the *wrapped* Hilbert primitive — what
    # the interpretation has to establish — written out in the target and
    # checked. `G` here is a concrete one-formula context rather than a
    # metavariable, which is the honest limit of what a proof can state: a
    # sequent proof's lines are sentences, so uniformity in Γ is what the rules
    # give and not something a proof can say (see the finding below).
    _source, target = two_systems(db, client, "discharge@example.com")

    # ax-1: `Γ ⊢ (P → (Q → P))`
    assert verify_proof(client, db, target, "\n".join([
        "G , P ⊢ P [id]",
        "G , P , Q ⊢ P [WL, 1]",
        "G , P ⊢ (Q → P) [→R, 2]",
        "G ⊢ (P → (Q → P)) [→R, 3]",
    ]))["success"] is True

    # ax-3's shape, on the transposition's easy half: what matters here is that
    # the target *can* discharge an implication-headed axiom by →R, which is the
    # move all three propositional axioms end on.
    assert verify_proof(client, db, target, "\n".join([
        "G , ¬P ⊢ ¬P [id]",
        "G ⊢ (¬P → ¬P) [→R, 1]",
    ]))["success"] is True

    # MP: with both of the wrapped premises in the antecedent,
    # `Γ, P, (P → Q) ⊢ Q` — which is modus ponens as a sequent, and what cut
    # then discharges against `Γ ⊢ P` and `Γ ⊢ (P → Q)`. Written this way
    # because a sequent proof's lines are *sentences*: it cannot assume its
    # premises the way an inference rule states them, so the derivation that can
    # be written down is the one that carries them in the context.
    assert verify_proof(client, db, target, "\n".join([
        "G , P , Q ⊢ Q [id]",
        "G , P ⊢ P [id]",
        "G , P , (P → Q) ⊢ Q [→L, 2, 1]",
    ]))["success"] is True


def test_generalisation_cannot_be_discharged_uniformly_in_the_context(db, client):
    # **The finding**, and the reason S2's edge is the propositional fragment's
    # rather than the whole of FOL's (§6.3 sketched it with `ax-gen` among the
    # obligations).
    #
    # An interpretation is sound because each source primitive's *image* is
    # derivable — uniformly in the extras, since Γ is universally quantified in
    # every transferred theorem. `ax-gen` is `⊢ P ⟹ ⊢ ∀x P`, and its image is
    # `Γ ⊢ P ⟹ Γ ⊢ ∀x P`, which is ∀R without ∀R's proviso. So it is derivable
    # exactly when `x` does not occur in Γ, and *not* uniformly.
    #
    # Both halves are here, and the pair is the argument: the wrap holds for a
    # context that does not mention `a`, and fails for one that does. A discharge
    # is a claim about all Γ, so one counterexample is what settles it.
    _source, target = two_systems(db, client, "ax-gen@example.com", generalisation=True)

    assert verify_proof(client, db, target, "\n".join([
        "c = c ⊢ a = a [refl]",
        "c = c ⊢ ∀a a = a [∀R, 1]",
    ]))["success"] is True
    assert verify_proof(client, db, target, "\n".join([
        "a = a ⊢ a = a [refl]",
        "a = a ⊢ ∀a a = a [∀R, 1]",
    ]))["success"] is False


def test_a_closed_template_is_what_a_source_with_generalisation_needs(db, client):
    # The finding's constructive half, and the reason S2 is not blocked by it.
    #
    # The obligation `ax-gen` cannot meet is uniformity in Γ — and uniformity is
    # demanded only because the template *introduces* Γ. A template with no
    # extras demands nothing: `∅ ⊢ P ⟹ ∅ ⊢ ∀x P` is ∀R at a context that
    # mentions no variable at all, so `occurs(x, ∅)` is false and the primitive
    # discharges. The whole of FOL crosses, at the empty context.
    #
    # What it costs is exactly one step, and the three assertions are that cost:
    # the wrapped theorem stands at `∅`, does *not* stand at a non-empty context,
    # and reaches one by weakening — which is the author's step to cite rather
    # than something the edge can claim on their behalf.
    source, target = two_systems(db, client, "closed@example.com", generalisation=True)
    promote_into(db, source, IDENTITY_LAW)
    interpret(
        db, source, target,
        template="∅ ⊢ {wff}",
        extras=None,
        obligations=[*OBLIGATIONS, ("ax-gen", "∀R")],
    )

    assert verify_proof(client, db, target, "∅ ⊢ (P → P) [id-law]")["success"] is True
    assert verify_proof(client, db, target, "A ⊢ (P → P) [id-law]")["success"] is False
    assert verify_proof(client, db, target, "\n".join([
        "∅ ⊢ (P → P) [id-law]",
        "∅ , A ⊢ (P → P) [WL, 1]",
    ]))["success"] is True


def test_a_theorem_wrapped_here_reads_in_this_system_s_notation(db, client):
    # The stored entry, read back. Promotion scans a statement's *text* for the
    # metavariables it was given, so the wrapped spec has to render in the
    # target's notation rather than carry the source's — which is why the wrap
    # re-renders from its own term (`_wrapped`), on the same reasoning a rename
    # re-renders from its translated one.
    source, target = two_systems(db, client, "render@example.com")
    promote_into(db, source, IDENTITY_LAW)
    interpret(db, source, target)

    promoted = _promote_across(db, target, ["id-law"])
    theorem = promoted["id-law"]
    assert theorem.deduction.schema_term is not None
    assert theorem.deduction.schema_term.to_string() == "G ⊢ (P → P)"
    # And the context is a metavariable of the promoted theorem, which is what
    # lets a citing line instantiate it.
    assert "G" in theorem.deduction.schema_term.free_vars()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _statement_term(system, text: str, metavariables: dict[str, str]):
    """The kernel term ``text`` composes to in ``system``, held schematic."""
    from website.logical.promotion import promote_spec

    promoted = promote_spec(
        system,
        TheoremSpec(label="probe", statement=text, metavariables=metavariables),
    )
    assert promoted.deduction.schema_term is not None
    return promoted.deduction.schema_term


def _promote_across(db_path, system_id: str, labels: list[str]) -> dict:
    """Promote ``labels`` in ``system_id``, through every layer that reaches it."""
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            system = session.get(FormalSystem, uuid.UUID(system_id))
            chain = _chain(session, system)
            spec, _library = effective_library(chain)
            built = build_spec(spec)["system"]
            context = copy(built.context)
            context.variables.update(built.build_context.variables)
            return load_theorems(
                session, _library_chain(session, chain, spec), labels, built, context
            )
    finally:
        engine.dispose()


def _library_chain(session, chain, spec):
    """The chain a verify would read, edges included."""
    from app.db import LibraryChain, related_layers
    from app.db.promoted_theorems_mapping import LibraryLayer
    from website.logical.declarative import layered_spec, library_digest

    from app.db.systems_mapping import system_to_spec

    specs = [system_to_spec(system) for system in chain]
    layers = [
        LibraryLayer(system.id, library_digest(layered_spec(specs[: index + 1])))
        for index, system in reversed(list(enumerate(chain)))
    ]
    return LibraryChain(tuple(layers) + tuple(related_layers(session, chain, spec)))
