"""Finding a label from the words a paper used for it.

§4.5 of docs/informal-source-ingestion-roadmap.md over HTTP. The route's job is
to answer a question no structural search can be asked — a model holding the
*name* "Cantor–Schröder–Bernstein" and no term — so what these pin is mostly
about honesty rather than recall: that the ranking is one a caller can account
for, that a hit is followable, that the haystack's size is reported so an empty
answer is readable, and that nothing draft becomes searchable on the way.

The fixtures are `tests/test_descriptions_store`'s, since the rows searched here
are exactly the ones that suite stores.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi_users")
pytest.importorskip("aiosqlite")
pytest.importorskip("regex")

from fastapi.testclient import TestClient
from sqlalchemy import NullPool, create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

import app.auth.backend as backend
from app.db.descriptions import LabelDescriptionRow
from app.db.metamath_store import import_corpus
from app.db.models import Proof
from app.db.session import get_session
from app.main import app
from tests.database import (
    ON_POSTGRES,
    async_url,
    create_tables,
    database_url,
    enable_foreign_keys,
)
from app.db.label_search import EXCERPT_WIDTH, MAX_ALTERNATIVES, _excerpt
from tests.test_descriptions_api import LAYERED
from tests.test_descriptions_store import SOURCE
from tests.test_proofs_api import _TABLES
from tests.test_systems_api import _register_login
from website.logical.metamath import parse
from website.logical.metamath.setmm import LAYERS


@pytest.fixture
def db(tmp_path):
    db_path = database_url(tmp_path, "label_search")
    create_tables(db_path, _TABLES)

    async_engine = create_async_engine(async_url(db_path), poolclass=NullPool)
    enable_foreign_keys(async_engine.sync_engine)
    sessionmaker = async_sessionmaker(async_engine, expire_on_commit=False)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    yield db_path
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def client(db, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setattr(backend.cookie_transport, "cookie_secure", False)
    with TestClient(app) as test_client:
        yield test_client


def seed(db_path) -> tuple[str, dict[str, str]]:
    """The documented fixture: one of each kind of label, all four described."""
    engine = create_engine(db_path)
    try:
        with Session(engine) as session:
            report = import_corpus(session, parse(SOURCE), name="t")
            session.commit()
            proofs = {p.name: str(p.id) for p in session.scalars(select(Proof))}
            return str(report.system_id), proofs
    finally:
        engine.dispose()


def search(client, system_id: str, q: str, **params) -> dict:
    response = client.get(
        f"/api/formal-systems/{system_id}/labels", params={"q": q, **params}
    )
    assert response.status_code == 200, response.text
    return response.json()


def labels(body: dict) -> list[str]:
    return [hit["label"] for hit in body["items"]]


# ---------------------------------------------------------------------------
# What it finds
# ---------------------------------------------------------------------------


def test_a_word_in_the_prose_finds_the_label(client, db):
    # The whole point: `df-neg` is a `$a` with no proof, spelled nothing like the
    # word it is about, and reachable today only by already knowing its name.
    system_id, _ = seed(db)

    body = search(client, system_id, "negation")

    assert "df-neg" in labels(body)
    assert body["total"] == len(body["items"])


def test_the_label_itself_is_searchable(client, db):
    # A caller that already read `~ df-neg` in someone's prose has the label and
    # wants the record, not a name lookup — and typing it should not miss.
    system_id, _ = seed(db)

    body = search(client, system_id, "df-neg")

    assert labels(body)[0] == "df-neg"
    assert body["items"][0]["matched"] == "label"


def test_every_word_has_to_appear(client, db):
    # `AND`, not `OR`. A two-word query is a name; an `OR` over it returns
    # everything containing the commoner half, which on a corpus is everything.
    system_id, _ = seed(db)

    both = search(client, system_id, "define negation")
    assert labels(both) == ["df-neg"]

    # "define" alone reaches only df-neg; "wff" alone reaches the builders. The
    # conjunction of the two is empty even though each half is not.
    assert labels(search(client, system_id, "define wff")) == []
    assert set(labels(search(client, system_id, "wff"))) >= {"wi", "wn"}


def test_the_words_may_land_in_different_fields_of_one_label(client, db):
    # `AND` across the *record*, not within one field: "negation" is in df-neg's
    # title and "paragraph" only in its second paragraph, and a caller quoting a
    # paper is as likely to mix the two as not.
    system_id, _ = seed(db)

    assert labels(search(client, system_id, "negation paragraph")) == ["df-neg"]


# ---------------------------------------------------------------------------
# The ranking, and being able to account for it
# ---------------------------------------------------------------------------


def test_a_label_match_outranks_a_title_match_outranks_the_body(client, db):
    # The ranking a caller is asked to trust. "wn" is a label, `wn`'s own title
    # says "negation", and df-neg mentions negation throughout its body.
    system_id, _ = seed(db)

    body = search(client, system_id, "negation")
    found = {hit["label"]: hit["matched"] for hit in body["items"]}

    assert found["wn"] == "title"
    assert found["df-neg"] == "title"
    # And the title matches come before anything that only matched in prose.
    kinds = [hit["matched"] for hit in body["items"]]
    assert kinds == sorted(kinds, key=["label", "title", "text", "record"].index)


def test_matched_says_which_field_the_ranking_used(client, db):
    # Served because a ranking a caller cannot account for is one it has to
    # either trust blindly or ignore. "survives" appears only in df-neg's second
    # paragraph, so the hit must say `text` rather than imply a title match.
    system_id, _ = seed(db)

    (hit,) = search(client, system_id, "survives")["items"]
    assert hit["label"] == "df-neg"
    assert hit["matched"] == "text"


def test_a_body_match_carries_the_prose_around_it(client, db):
    # An excerpt is what makes a body hit judgeable without a second request.
    system_id, _ = seed(db)

    (hit,) = search(client, system_id, "survives")["items"]
    assert hit["excerpt"] is not None
    assert "survives" in hit["excerpt"]


def test_a_title_match_carries_no_excerpt(client, db):
    # None rather than the opening of the prose: an excerpt of text the query
    # never touched is an answer to a question nobody asked.
    system_id, _ = seed(db)

    (hit,) = [h for h in search(client, system_id, "df-neg")["items"] if h["label"] == "df-neg"]
    assert hit["matched"] == "label"
    assert hit["excerpt"] is None


def test_ties_are_broken_by_label_so_two_reads_are_two_of_the_same_page(client, db):
    # A rank with four values ties constantly, and without a total order page 2
    # of one read is not page 2 of the next.
    system_id, _ = seed(db)

    first = search(client, system_id, "wff", limit=1, offset=0)
    second = search(client, system_id, "wff", limit=1, offset=1)

    assert labels(first) + labels(second) == sorted(
        labels(search(client, system_id, "wff"))
    )
    assert first["total"] == second["total"]


# ---------------------------------------------------------------------------
# Being followable
# ---------------------------------------------------------------------------


def test_a_hit_that_is_a_proof_carries_its_id(client, db):
    # What makes a hit actionable rather than a name to look up again.
    system_id, proofs = seed(db)

    (hit,) = [h for h in search(client, system_id, "identity")["items"] if h["label"] == "id"]
    assert hit["proof_id"] == proofs["id"]
    assert hit["proof_title"] == "Principle of identity."


def test_a_hit_that_is_a_syntax_axiom_has_no_proof_to_open(client, db):
    # Null as often as not, and null is the honest answer: `df-neg` is a `$a`, it
    # is perfectly citable, and there is simply nothing to open.
    system_id, _ = seed(db)

    (hit,) = [h for h in search(client, system_id, "df-neg")["items"] if h["label"] == "df-neg"]
    assert hit["proof_id"] is None


def test_a_hit_names_the_layer_it_lives_on(client, db):
    # On a layered corpus the answer comes from a system that was not asked, and
    # a follow-up read has to be addressed to the one the label is stored against.
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            report = import_corpus(session, parse(LAYERED), name="c", plan=LAYERS)
            session.commit()
            system_ids = [str(found) for found in report.system_ids]
    finally:
        engine.dispose()

    leaf = system_ids[-1]
    (hit,) = [
        h
        for h in search(client, leaf, "propositional")["items"]
        if h["label"] == "fol-cites-pc"
    ]
    # Filed against the first-order layer, found from the set-theoretic one.
    assert hit["formal_system_id"] != leaf
    assert hit["formal_system_id"] in system_ids

    # And addressing the single-label read to the layer it named works.
    reachable = client.get(
        f"/api/formal-systems/{hit['formal_system_id']}/labels/fol-cites-pc"
    )
    assert reachable.status_code == 200, reachable.text


# ---------------------------------------------------------------------------
# The second haystack: proofs written here
# ---------------------------------------------------------------------------


def test_a_hand_authored_proof_is_searchable_by_its_own_title(client, db):
    # The half `label_descriptions` cannot hold. A proof created through the API
    # gets no description row, so searching only those would answer "what does
    # this system have about associativity" with the imported half of it.
    _register_login(client, "ada@example.com")
    system_id = client.post(
        "/api/formal-systems", json={"name": "Hand authored"}
    ).json()["id"]
    made = client.post(
        "/api/proofs",
        json={
            "name": "assoc",
            "formal_system_id": system_id,
            "title": "Conjunction is associative.",
            "description": "Proved by cases on the left conjunct.",
        },
    )
    assert made.status_code == 201, made.text

    body = search(client, system_id, "associative")
    assert labels(body) == ["assoc"]
    assert body["items"][0]["proof_id"] == made.json()["id"]

    # Its description is searched too, and reports itself as a body match.
    (hit,) = search(client, system_id, "cases")["items"]
    assert hit["matched"] == "text"
    assert "left conjunct" in hit["excerpt"]

    # And this is a *substring* match, which is the ceiling worth pinning rather
    # than discovering: "conjunct" reaches this proof through the word
    # "Conjunction" in its title, and ranks as the title match it is.
    assert search(client, system_id, "conjunct")["items"][0]["matched"] == "title"


def test_a_draft_proof_is_not_searchable_by_a_stranger(client, db):
    # The leak this route could be: a proof's title and description are its
    # author's until published, and a search that matched them would hand out
    # both plus the label — the same predicate a proof read applies.
    _register_login(client, "ada@example.com")
    system_id = client.post(
        "/api/formal-systems", json={"name": "Shared"}
    ).json()["id"]
    client.post(
        "/api/proofs",
        json={
            "name": "secret",
            "formal_system_id": system_id,
            "title": "Unpublished thoughts on compactness.",
        },
    )
    published = client.patch(f"/api/formal-systems/{system_id}", json={"published": True})
    assert published.status_code == 200, published.text

    # Its author finds it.
    assert labels(search(client, system_id, "compactness")) == ["secret"]

    # A stranger does not — and neither does an anonymous caller.
    client.post("/api/auth/logout")
    assert labels(search(client, system_id, "compactness")) == []
    _register_login(client, "bob@example.com")
    assert labels(search(client, system_id, "compactness")) == []


def test_one_row_per_label_when_a_label_is_both(client, db):
    # An imported `$p` is a description *and* a proof, and both haystacks match
    # it. Twice on the page is a reader with no way to tell which one a citation
    # would resolve to.
    system_id, proofs = seed(db)

    body = search(client, system_id, "identity")
    assert labels(body).count("id") == 1
    # And the corpus's record won, so the hit carries the description's title.
    (hit,) = [h for h in body["items"] if h["label"] == "id"]
    assert hit["title"] == "Principle of identity."
    assert hit["proof_id"] == proofs["id"]


# ---------------------------------------------------------------------------
# Honesty about what was searched
# ---------------------------------------------------------------------------


def test_an_empty_result_says_how_much_prose_it_looked_through(client, db):
    # What makes an empty answer readable. "the words are not in this corpus" and
    # "this corpus is undocumented" are the same empty list otherwise, and only
    # one of them means the search is finished.
    system_id, _ = seed(db)

    body = search(client, system_id, "cohomology")
    assert body["items"] == []
    assert body["total"] == 0
    assert body["documented"] == 5


def test_an_undocumented_system_says_so(client, db):
    # The other side of the same number: nothing matched because there is
    # nothing to match against.
    _register_login(client, "ada@example.com")
    system_id = client.post(
        "/api/formal-systems", json={"name": "Bare"}
    ).json()["id"]

    body = search(client, system_id, "anything")
    assert body["items"] == []
    assert body["documented"] == 0


def test_the_discouragement_markers_ride_along(client, db):
    # They matter more here than anywhere: this is the list a caller picks a
    # citation from, and `set.mm` discourages 5,169 of its own.
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            marked = SOURCE.replace(
                "$( Wff builder for negation. $)",
                "$( Wff builder for negation.  (New usage is discouraged.) $)",
                1,
            )
            report = import_corpus(session, parse(marked), name="t")
            session.commit()
            system_id = str(report.system_id)
    finally:
        engine.dispose()

    (hit,) = [
        h for h in search(client, system_id, "negation")["items"] if h["label"] == "wn"
    ]
    assert hit["discouraged_usage"] is True


# ---------------------------------------------------------------------------
# Paging, and the query itself
# ---------------------------------------------------------------------------


def test_a_page_reports_the_whole_match_count(client, db):
    system_id, _ = seed(db)

    page = search(client, system_id, "wff", limit=1)
    assert len(page["items"]) == 1
    assert page["total"] == len(labels(search(client, system_id, "wff")))
    assert page["limit"] == 1
    assert page["offset"] == 0


def test_a_blank_query_matches_nothing_rather_than_everything(client, db):
    # An empty `AND` is vacuously true; without this it would page the corpus.
    system_id, _ = seed(db)

    body = search(client, system_id, "   ")
    assert body["items"] == []
    assert body["total"] == 0
    # And it still says what it looked through, so the caller can tell the
    # difference between a bad query and a bare system.
    assert body["documented"] == 5


def test_a_wildcard_in_the_query_is_a_character(client, db):
    # `LIKE` reads `%` and `_` as syntax, and an unescaped one silently widens
    # the search rather than failing. `ax-1`'s title spells `_Simp_`.
    system_id, _ = seed(db)

    assert labels(search(client, system_id, "_simp_")) == ["ax-1"]
    # A bare wildcard matches nothing, where unescaped it would match every label.
    assert labels(search(client, system_id, "%")) == []


def test_a_system_the_caller_cannot_read_is_a_404(client, db):
    # The draft-system gate, checked before any prose is searched.
    _register_login(client, "ada@example.com")
    system_id = client.post(
        "/api/formal-systems", json={"name": "Draft"}
    ).json()["id"]
    client.post("/api/auth/logout")

    response = client.get(
        f"/api/formal-systems/{system_id}/labels", params={"q": "anything"}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# What the review found: four ways an answer could be true of the wrong thing
# ---------------------------------------------------------------------------


def test_a_hit_links_to_the_proof_on_its_own_layer(client, db):
    # A hit *is* a row on a known layer, so resolving its link nearest-first
    # answers about a different one: two systems in a chain may declare the same
    # name, and the ancestor's hit would carry the descendant's proof id.
    _register_login(client, "ada@example.com")
    parent = client.post("/api/formal-systems", json={"name": "Parent"}).json()["id"]
    theirs = client.post(
        "/api/proofs",
        json={
            "name": "dup",
            "formal_system_id": parent,
            "title": "Compactness of the Stone space.",
        },
    )
    assert theirs.status_code == 201, theirs.text

    # A child may only inherit from a published parent.
    client.patch(f"/api/formal-systems/{parent}", json={"published": True})
    made = client.post(
        "/api/formal-systems", json={"name": "Child", "inherits_from_id": parent}
    )
    assert made.status_code == 201, made.text
    child = made.json()["id"]

    mine = client.post(
        "/api/proofs",
        json={
            "name": "dup",
            "formal_system_id": child,
            "description": "An unrelated note.",
        },
    )
    assert mine.status_code == 201, mine.text

    # "stone" is only in the parent's title, so the parent's row is the only hit
    # — and the link on it must be the parent's proof, not the nearer namesake.
    (hit,) = search(client, child, "stone")["items"]
    assert hit["formal_system_id"] == parent
    assert hit["proof_id"] == theirs.json()["id"]
    assert hit["proof_title"] == "Compactness of the Stone space."


def test_words_split_across_fields_are_a_record_match_not_a_prose_one(client, db):
    # `wi` is the label and "wff" is in the title, so *no single field* holds both
    # — and calling that a text match is a claim about a body that contains
    # neither word. It also produced `matched: "text"` beside `excerpt: null`,
    # which the schema says cannot happen.
    system_id, _ = seed(db)

    (hit,) = [h for h in search(client, system_id, "wi wff")["items"] if h["label"] == "wi"]
    assert hit["matched"] == "record"

    # And the invariant that broke: a `text` match always has an excerpt.
    for word in ("survives", "paragraph"):
        for found in search(client, system_id, word)["items"]:
            if found["matched"] == "text":
                assert found["excerpt"] is not None


def test_the_words_actually_searched_come_back(client, db):
    # The cap would otherwise be a silent lie: the contract is that every word
    # appears in every hit, so dropping the ninth answers a *broader* question
    # and every extra row is a false positive nobody can identify.
    system_id, _ = seed(db)

    body = search(client, system_id, "  Negation   DEFINE negation ")
    # Lowercased and deduplicated, in the order given — one list per alternative.
    assert body["searched"] == [["negation", "define"]]

    long_query = " ".join(f"w{n}" for n in range(12))
    assert len(search(client, system_id, long_query)["searched"][0]) == 8


def test_an_excerpt_always_contains_what_was_searched_for():
    # The word-boundary trim is a tidiness and does not get to cost the thing
    # being excerpted. A run longer than the window with no space in it — a URL,
    # a long token — put the first space *past* the match, and the excerpt came
    # back containing none of the query.
    body = "x" * (EXCERPT_WIDTH * 2) + "needle and then some ordinary prose"
    found = _excerpt(body, ["needle"])
    assert found is not None
    assert "needle" in found

    # The ordinary case is unchanged: a slice on word boundaries, ellipsed.
    prose = " ".join(["filler"] * 100) + " needle " + " ".join(["more"] * 100)
    ordinary = _excerpt(prose, ["needle"])
    assert "needle" in ordinary
    assert ordinary.startswith("…") and ordinary.endswith("…")
    assert not ordinary.startswith("…iller")

    # And a word the body does not carry has nothing to point at.
    assert _excerpt(prose, ["absent"]) is None


def test_the_single_label_route_still_resolves(client, db):
    # `/labels` and `/labels/{label}` are two routes on one prefix, and a
    # collision between them would be silent — the search would answer for a
    # label read, or the other way round.
    system_id, _ = seed(db)

    one = client.get(f"/api/formal-systems/{system_id}/labels/df-neg")
    assert one.status_code == 200
    assert one.json()["label"] == "df-neg"


# ---------------------------------------------------------------------------
# Query expansion: several alternatives in one call
# ---------------------------------------------------------------------------
#
# The lexical route's ceiling is that a query sharing no *word* with the prose
# scores nothing however well it describes it, and no lexical method can lift
# that — a paper saying "every infinite subset of a compact space has a limit
# point" shares no stem with "Bolzano-Weierstrass theorem". What can lift it is
# the caller, which is a language model and knows the name. So the API ranks
# documents against terms and the consumer decides what the terms are; these
# cover the API's half of that (§4.5).


def search_many(client, system_id: str, queries: list[str], **params) -> dict:
    response = client.get(
        f"/api/formal-systems/{system_id}/labels",
        params=[("q", q) for q in queries] + list(params.items()),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_alternatives_are_searched_together_as_one_page(client, db):
    # One call rather than one per guess: the same page, the same total, and the
    # ranking sees every alternative at once rather than the caller merging N
    # pages itself.
    system_id, _ = seed(db)

    body = search_many(client, system_id, ["negation", "implication"])

    found = set(labels(body))
    assert "df-neg" in found and "wi" in found
    assert body["total"] == len(body["items"])
    # One token list per alternative, in the order given.
    assert body["searched"] == [["negation"], ["implication"]]


def test_a_hit_says_which_alternative_found_it(client, db):
    # The feedback half of expansion: a model that proposed five phrasings learns
    # which one the corpus actually uses, which is what it carries into the next
    # lookup.
    system_id, _ = seed(db)

    body = search_many(client, system_id, ["cohomology", "negation"])

    assert body["searched"] == [["cohomology"], ["negation"]]
    # Nothing matched the first guess; everything here came from the second.
    assert {hit["matched_query"] for hit in body["items"]} == {1}


def test_an_alternative_that_matches_nothing_costs_nothing(client, db):
    # Expansion is guessing, so most guesses miss. A miss must not narrow the
    # result — the alternatives are an `OR`, unlike the words within one.
    system_id, _ = seed(db)

    alone = labels(search(client, system_id, "negation"))
    expanded = labels(search_many(client, system_id, ["negation", "cohomology"]))

    assert expanded == alone


def test_the_best_alternative_sets_the_rank_not_the_first(client, db):
    # Ordered by rank rather than by variant, so a weak hit on the caller's first
    # guess does not outrank a label hit on its second. `wn` is a label; the
    # word "negation" only reaches it through its title.
    system_id, _ = seed(db)

    body = search_many(client, system_id, ["negation", "wn"])

    (hit,) = [h for h in body["items"] if h["label"] == "wn"]
    assert hit["matched"] == "label"


def test_a_single_query_still_answers_exactly_as_before(client, db):
    # The compatibility case: one `q` is one alternative, and nothing about the
    # single-query surface moved except the shape of `searched`.
    system_id, _ = seed(db)

    one = search(client, system_id, "negation")
    same = search_many(client, system_id, ["negation"])

    assert labels(one) == labels(same)
    assert one["searched"] == same["searched"] == [["negation"]]
    assert {hit["matched_query"] for hit in one["items"]} == {0}


def test_the_alternative_credited_is_the_one_that_earned_the_rank(client, db):
    # The ranking takes the best tier across alternatives, so attributing by
    # "first to match anywhere" let a broad guess steal credit from the specific
    # one — inverting the very signal the field exists to give. `wff` reaches
    # `wn` only through its title; `wn` is the label.
    system_id, _ = seed(db)

    body = search_many(client, system_id, ["wff", "wn"])

    (hit,) = [h for h in body["items"] if h["label"] == "wn"]
    assert hit["matched"] == "label"
    # …so the credit goes to the alternative that reached the label tier.
    assert hit["matched_query"] == 1


def test_the_excerpt_comes_from_the_alternative_credited(client, db):
    # Flattening every alternative's tokens let the excerpt come from one the hit
    # is not attributed to — and gave prose to label matches that had none.
    system_id, _ = seed(db)

    alone = search(client, system_id, "df-neg")["items"][0]
    with_other = [
        h
        for h in search_many(client, system_id, ["df-neg", "falsehood"])["items"]
        if h["label"] == "df-neg"
    ][0]

    assert alone["excerpt"] is None
    # Credited to `df-neg`, which is a label match, so still no excerpt.
    assert with_other["matched_query"] == 0
    assert with_other["excerpt"] is None


def test_an_empty_alternative_keeps_the_others_indices(client, db):
    # Dropping a blank alternative silently shifted every index after it, so
    # `matched_query` stopped indexing what the caller sent.
    system_id, _ = seed(db)

    body = search_many(client, system_id, ["", "negation"])

    assert [hit["matched_query"] for hit in body["items"]] == [1] * len(body["items"])
    # And `searched` keeps the blank in place, so the two line up.
    assert body["searched"] == [[], ["negation"]]


def test_too_many_alternatives_are_refused(client, db):
    # Words within an alternative were capped from the start and the alternatives
    # themselves were not, leaving the expensive axis unbounded on a route an
    # anonymous caller may hit: 500 of them cost 1.59 s in plan time alone.
    system_id, _ = seed(db)

    response = client.get(
        f"/api/formal-systems/{system_id}/labels",
        params=[("q", f"w{n}") for n in range(MAX_ALTERNATIVES + 1)],
    )
    assert response.status_code == 422, response.text

    # And the cap itself is accepted.
    ok = client.get(
        f"/api/formal-systems/{system_id}/labels",
        params=[("q", f"w{n}") for n in range(MAX_ALTERNATIVES)],
    )
    assert ok.status_code == 200, ok.text


def test_the_credit_uses_the_database_case_rules_not_python_s(client, db):
    # Attribution was recomputed in Python and the rank came from SQL, so the two
    # agreed only where their case folding did. SQLite's `lower` is ASCII-only and
    # Python's is Unicode: for a label `Ω`, the alternative `ω` was an *exact label
    # match* in Python and no match at all in SQL, and the hit came back claiming
    # the tier one alternative reached beside the index of another.
    system_id, _ = seed(db)
    engine = create_engine(db)
    try:
        with Session(engine) as session:
            session.add(
                LabelDescriptionRow(
                    formal_system_id=uuid.UUID(system_id),
                    label="Ω",
                    title="fallback",
                    text="",
                )
            )
            session.commit()
    finally:
        engine.dispose()

    body = search_many(client, system_id, ["ω", "fallback"])

    (hit,) = [h for h in body["items"] if h["label"] == "Ω"]
    # Which alternative wins is the database's answer, and the two engines give
    # different ones — which is the whole point. Postgres folds Unicode, so `ω`
    # *is* an exact label match and takes the first alternative; SQLite's `lower`
    # is ASCII-only, so it never matched and the credit falls to the title on the
    # second. What is being pinned either way is that the credit agrees with the
    # rank, rather than being recomputed in Python and disagreeing with it.
    if ON_POSTGRES:
        assert hit["matched"] == "label"
        assert hit["matched_query"] == 0
    else:
        assert hit["matched"] == "title"
        assert hit["matched_query"] == 1
