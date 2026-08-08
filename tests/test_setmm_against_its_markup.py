"""`setmm.py`'s hand-written tables, checked against what the file declares.

Three of the things Edifyce has to know about `set.mm` are written *in* `set.mm`,
in its ``$j`` blocks, and were transcribed here by hand. Now that the blocks can
be read (:mod:`website.logical.metamath.markup`), the transcription can be
checked — so a table that drifts from the corpus fails here rather than misreading
a later revision in silence.

**Not derived from them, and the distinction is the point.** A table stays a table
because Edifyce imports any `.mm` and most carry no ``$j`` at all; reading one
where it exists would make the behaviour of an import depend on whether the file
happened to annotate itself. What the directives are good for is *agreement*: they
are the file's own account, and where the two disagree one of them is wrong.

The fourth table — ``BINDERS`` — is deliberately **not** checked, and that is the
finding rather than an omission. See the last test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("regex")

from website.logical.metamath import parse
from website.logical.metamath.markup import by_keyword, markup_of
from website.logical.metamath.parser import ASSERTION_TYPECODE
from website.logical.metamath.setmm import BINDERS, EQUIVALENCES, RESTATEMENTS

# The corpus is a 50 MB download, so these run against the fragment of its `$j`
# that carries the declarations in question — quoted verbatim, blocks and all.
# What they pin is that the *tables* say what the file says; that the file says it
# is `set.mm`'s business.
DECLARATIONS = r"""
$( $j syntax 'wff'; syntax '|-' as 'wff'; unambiguous 'klr 5'; $)
$( $j primitive 'wn'; $)
$( $j primitive 'wi'; $)
$( $j justification 'bijust' for 'df-bi'; $)
$( $j equality 'wb' from 'biid' 'bicomi' 'bitri'; definition 'dfbi1' for 'wb'; $)
$( $j syntax 'setvar'; bound 'setvar'; $)
$( $j equality 'wceq' from 'eqid' 'eqcomi' 'eqtri'; $)
$( $j free_var 'wsb' with 'y'; $)
$( $j free_var 'wcdeq' with 'x' 'y'; $)
$c |- wff $.
$v ph $.
wph $f wff ph $.
"""


@pytest.fixture(scope="module")
def declared():
    return markup_of(parse(DECLARATIONS).comments)


def test_the_equivalence_connectives_are_the_ones_the_file_calls_equalities(declared):
    # `EQUIVALENCES` decides which logical `$a` may be imported as a *definition*,
    # which is a licence to rewrite in both directions — so a wrong entry is not a
    # cosmetic error. `set.mm` names the same two.
    stated = {d.subject for d in by_keyword(declared, "equality")}

    assert stated == set(EQUIVALENCES) == {"wb", "wceq"}


def test_the_restatement_is_the_one_the_file_calls_a_definition(declared):
    # `df-bi` defines `<->` and so cannot be stated over it; `dfbi1` is the same
    # content the ordinary way round. The table was written from this directive —
    # this is the check that it still says so.
    (stated,) = list(by_keyword(declared, "definition"))

    assert stated.subject == "dfbi1"
    assert stated.clause("for") == ("wb",)
    assert set(RESTATEMENTS.values()) == {"dfbi1"}
    # And the key is the statement `dfbi1` restates, which the file says in the
    # other direction: `justification 'bijust' for 'df-bi'`.
    assert set(RESTATEMENTS) == {"df-bi"}


def test_the_assertion_typecode_is_the_one_the_file_declares(declared):
    # `ASSERTION_TYPECODE` separates a statement of *truth* from a declaration of
    # notation, which is the distinction an import is built on. It is a parameter
    # of the reader because Metamath fixes no such keyword — and `set.mm` says
    # which one it chose: `syntax '|-' as 'wff'`.
    (stated,) = [d for d in by_keyword(declared, "syntax") if d.clause("as")]

    assert stated.subject == ASSERTION_TYPECODE == "|-"
    assert stated.clause("as") == ("wff",)


def test_the_bindable_sort_is_the_one_the_file_calls_bound(declared):
    # `bound 'setvar'` is the file saying which typecode a binder ranges over,
    # which is what `_validate_constant_declarations` refuses a `denotes_constant`
    # against. Every production in `BINDERS` binds a slot of that sort.
    (stated,) = list(by_keyword(declared, "bound"))

    assert stated.subject == "setvar"


def test_the_binder_table_is_not_derivable_from_the_markup(declared):
    """The finding, pinned so it is not re-attempted the obvious way.

    ``$j`` looks like it should carry ``BINDERS``, and it does not. What it
    carries is ``bound 'setvar'`` — *which sort* is bindable, one directive — and
    ``free_var``, an **exception list** naming the slots that look like binders and
    are not. Two of those, against 28 productions in the table.

    So the file declares the default and the exceptions to it, and never the thing
    itself: nothing in ``$j`` says that the `x` of ``A. x ph`` scopes over `ph`
    while the `A` of ``A. x e. A ph`` does not. `setmm.BINDERS` is read off each
    syntax axiom's *statement*, which is where the answer actually is, and this
    test exists because the roadmap once claimed otherwise.
    """
    exceptions = {d.subject for d in by_keyword(declared, "free_var")}
    assert exceptions == {"wsb", "wcdeq"}

    # And the two exceptions do not even relate to the table the same way, which
    # is the sharpest form of the point. `wsb` is *in* it — `[ y / x ] ph` binds
    # `x` and the directive says the `y` beside it stays free — so there the
    # exception qualifies an entry. `wcdeq` is **absent**, because nothing about
    # it binds at all, so there the same directive qualifies nothing.
    assert "wsb" in BINDERS and BINDERS["wsb"] == {"x": ["ph"]}
    assert "wcdeq" not in BINDERS

    # Two entries against 28, naming what does not bind. It is not the table.
    assert len(exceptions) * 10 < len(BINDERS)


def test_every_declaration_checked_here_appears_in_the_real_corpus():
    """The fragment above is quoted, not invented — checked when the file is here.

    Skipped without it, since the corpus is a 50 MB download and CI has no copy.
    What it guards against is the fragment drifting into a fiction that the tests
    above then agree with.
    """
    corpus = Path(__file__).resolve().parent.parent / "set.mm"
    if not corpus.exists():
        pytest.skip("set.mm is not checked out; the fragment above is its quotation")

    real = markup_of(parse(corpus.read_text(encoding="utf-8")).comments)
    quoted = markup_of(parse(DECLARATIONS).comments)

    for directive in quoted:
        assert directive in real, directive
