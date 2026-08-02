"""A `.mm` file's own ``$t`` map, folded over terms as production templates.

Metamath declares one rendering per *token*. Substituting those into a statement
gives soup; folding them into the *productions* they appear in, and then folding
those over the term, keeps the structure the tree already has. This is the whole
of the bridge, and what it buys is that `set.mm`'s ASCII reads as mathematics.
"""

from __future__ import annotations

import pytest

pytest.importorskip("regex")

from website.logical.declarative import build_system
from website.logical.metamath import build_spec, parse
from website.logical.metamath.definitions import statement_of
from website.logical.metamath.display import projection_for, unicode_projection
from website.logical.metamath.typesetting import typesetting_of
from website.logical.rendering import render

SOURCE = r"""
$( $t
    althtmldef "e." as ' &isin; ';
    althtmldef "->" as ' &rarr; ';
    althtmldef "A." as '&forall;';
    althtmldef "RR" as '&#8477;';
    althtmldef "ph" as '<SPAN CLASS=wff STYLE="color:blue">&#x1D711;</SPAN>';
$)
$c |- wff class setvar ( ) -> e. A. RR $.
$v ph ps x A B $.
wph $f wff ph $.
wps $f wff ps $.
vx $f setvar x $.
cA $f class A $.
cB $f class B $.
cr $a class RR $.
cv $a class x $.
wi $a wff ( ph -> ps ) $.
wcel $a wff A e. B $.
wal $a wff A. x ph $.
ax-1 $a |- ( ph -> ( ps -> ph ) ) $.
"""


def built():
    database = parse(SOURCE)
    system = build_system(build_spec(database, name="t"))
    typesetting = typesetting_of(database.comments)
    return database, system, typesetting


def test_the_projection_respells_a_statement() -> None:
    database, system, typesetting = built()
    projection = unicode_projection(system.build_context, typesetting)

    term = statement_of(database.assertions["ax-1"], system)

    assert term.to_string() == "( ph -> ( ps -> ph ) )"
    # `ph` is an atom production, so it is re-spelled by the same map that handles
    # the operators — and its `<SPAN>` markup is stripped on the way through.
    assert render(term, projection) == "( 𝜑 → ( ps → 𝜑 ) )"


def test_an_unprojected_render_is_unchanged() -> None:
    # The property the whole thing rests on: a caller asking for no projection
    # sees exactly what it saw before projections existed.
    database, system, _ = built()

    term = statement_of(database.assertions["ax-1"], system)

    assert render(term) == term.to_string()


def test_spacing_comes_from_the_source_template_not_the_map() -> None:
    # A `$t` rendering carries its own padding (`' &isin; '`), which is HTML's
    # business. The production template already says where the spaces go, so the
    # mapped token is trimmed into the slot — otherwise every operator would
    # render double-spaced.
    database, system, typesetting = built()
    projection = unicode_projection(system.build_context, typesetting)

    assert projection.templates["wi"] == (
        ("lit", "( "), ("slot", "ph"), ("lit", " → "), ("slot", "ps"), ("lit", " )")
    )


def test_a_production_with_no_mapped_token_is_left_out() -> None:
    # The projection stays the size of what it changes, so a partial `$t` map — or
    # one for a database that declares more notation than it renders — costs
    # nothing per unmapped production.
    database, system, typesetting = built()
    projection = unicode_projection(system.build_context, typesetting)

    assert "cv" not in projection.templates
    assert {"wi", "wcel", "wal", "cr"} <= set(projection.templates)


def test_an_atom_is_respelled_from_its_own_token() -> None:
    database, system, typesetting = built()
    projection = unicode_projection(system.build_context, typesetting)

    assert projection.templates["cr"] == (("lit", "ℝ"),)


def test_a_plain_token_map_needs_no_typesetting_block() -> None:
    # `projection_for` takes tokens rather than a `$t`, so a database with no
    # block — or a caller with its own overrides — is served by the same path.
    _database, system, _ = built()
    projection = projection_for(system.build_context, {"->": "⊃"}, name="custom")

    assert projection.name == "custom"
    assert projection.templates["wi"] == (
        ("lit", "( "), ("slot", "ph"), ("lit", " ⊃ "), ("slot", "ps"), ("lit", " )")
    )
