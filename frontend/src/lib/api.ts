import { API_BASE_URL } from './config';

// ---------------------------------------------------------------------------
// Response shapes — mirror app/schemas.py and the proof `.data()` payload.
// ---------------------------------------------------------------------------

export interface HealthResponse {
	status: string;
}

/** One antecedent slot of a rule, and how the citation fared against it.
 *  Mirrors `SlotReportOut` in app/schemas.py. */
export interface SlotReport {
	index: number;
	/** The slot's schema as the rule states it — what a line must look like to
	 *  fill it. A slot with no `candidates` is a premise the proof is missing. */
	schema: string;
	candidates: number[];
}

/** Why a line is not established, as data beside the sentence. Mirrors
 *  `FailureOut` in app/schemas.py.
 *
 *  Fields past `code` and `message` are absent unless that code carries them: a
 *  `side-condition` names the proviso, a `slot-unsatisfied` names the slot, and a
 *  `hole` adds nothing. `code === 'hole'` is an open goal rather than a mistake. */
export interface Failure {
	code: string;
	message: string;
	rule?: string | null;
	reference?: string | null;
	lines?: number[];
	expected?: number | null;
	given?: number | null;
	slots?: SlotReport[];
	proviso?: string | null;
	definitions?: string[];
}

export interface ProofLine {
	valid: boolean;
	// The number a citation names this line by. Null for a line no citation can
	// reach (a blank line, or commentary), so it is not a text-line index.
	// Optional only because a proof verified before citation numbering existed
	// has a cached payload without the field — the viewer renders those at the
	// row position they were numbered by until the proof is checked again.
	number?: number | null;
	behaviour: string | null;
	name: string | null;
	invalid_message: string | null;
	/** The same verdict as data. Optional because a proof verified before this
	 *  existed has a cached payload without the field. */
	failure?: Failure | null;
	warning_message: string | null;
	reference: string | null;
	label: string | null;
	display: string | null;
	indent: number;
}

export interface ProofData {
	indicator: 'ok' | 'warning' | 'error' | string;
	lines: ProofLine[];
}

export interface VerifyResponse {
	success: boolean;
	errors: string[];
	proof: ProofData | null;
	/** Lines stated as open goals rather than proved, by citation number. A proof
	 *  with holes is unfinished, not wrong — `success` is false for both. */
	holes?: number[];
	/** Whether every failing line is a hole: nothing is wrong, there is just work
	 *  left. False with holes present means both, and the errors come first. */
	only_holes?: boolean;
}

/** A justification for one line, proposed as structure rather than as text.
 *  Mirrors `CitationProposal` in app/schemas.py.
 *
 *  `{line: 7, rule: 'MP', antecedents: [4, 6]}` is a label and three integers —
 *  already unambiguous, and needing none of the system's citation syntax. `rule`
 *  may be the hole keyword (`'?'`), which parks the line as an open goal.
 *
 *  Lines are named by their **citation number**, the handle an antecedent edge
 *  already uses, not by an index into the source. */
export interface CitationProposal {
	line: number;
	rule: string;
	antecedents?: number[];
	/** Commit it to the source. Omitted, this is a dry run — so several
	 *  justifications can be tried without undoing the ones that failed. */
	apply?: boolean;
}

/** What a proposed justification would do, or did. Mirrors `CitationOutcome`. */
export interface CitationOutcome {
	line: number;
	/** The reference text the proposal formatted to, e.g. `"MP, 4, 6"`. */
	citation: string;
	accepted: boolean;
	/** Why not, when not — the same structured reason a verify reports, so a
	 *  rejected proposal names the next goal rather than only saying no. */
	failure: Failure | null;
	applied: boolean;
	/** Where the proof stands afterwards. Populated on an applied proposal only. */
	valid: boolean | null;
	holes: number[];
	only_holes: boolean;
}

/** A term named structurally: by reference, by production, or as a variable.
 *  Mirrors `TermProposalIn` in app/schemas.py.
 *
 *  Exactly one of `ref` and `constructor`. `ref` names a term that already
 *  exists — the reason this is worth having, since an interned term is shared and
 *  a caller can point at a subterm instead of restating it. `constructor` names a
 *  production of the system's own grammar, so the vocabulary is closed.
 *
 *  A metavariable is deliberately not among them: a proof line states a *ground*
 *  formula, and a schematic variable belongs to a rule schema. */
export interface TermProposal {
	ref?: string;
	constructor?: string;
	slots?: Record<string, TermProposal>;
	/** The token a leaf stands for. A constant atom's comes from the production
	 *  itself, so it may be omitted there and may not contradict it. */
	literal?: string;
	/** The sort a term *inhabits* — only a defined form carries one. */
	sort?: string;
}

/** A new line, stated as structure and justified as structure. Mirrors
 *  `LineProposal`.
 *
 *  `before` is the citation number to insert ahead of — what a goal-directed
 *  caller wants, since a rule's antecedents must precede its conclusion. Omitted,
 *  the line is appended. `rule` defaults to the hole keyword, because stating a
 *  premise you have not proved *is* an open goal. */
export interface LineProposal {
	statement: TermProposal;
	rule?: string;
	antecedents?: number[];
	before?: number;
	/** Which of the system's line types to write this as. Naming one whose type
	 *  declares a scope is how a subproof is *opened*; the anchor line's own type
	 *  is used when this is omitted. A type the proof has no line of yet is
	 *  composed from its declared shape, so a first subproof is reachable. */
	line_type?: string;
	scope?: ScopePlacement;
	apply?: boolean;
}

/** Where a new line sits relative to the subproof opened at `opener`.
 *
 *  A subproof is delimited by *indentation* — a line indented past an opener is
 *  inside it, one at or left of the opener closes it — so placing a line in one
 *  means choosing its indent, and a caller should not need to know a proof's
 *  indent convention. Hence the opener's citation number, which is what a
 *  discharge cites anyway and what `structure()` reports.
 *
 *  `outside` is the position a **discharge** is written at, and the only way back
 *  out. Note a subproof cannot be rejoined once closed: indenting does not reopen
 *  it, so `inside` needs a `before` that falls within the block. */
export interface ScopePlacement {
	opener: number;
	placement: 'inside' | 'outside';
}

/** What a proposed line would do, or did. Mirrors `LineOutcome`. */
export interface LineOutcome {
	line: number;
	/** The line as it would be written — the source its structure became. */
	display: string;
	accepted: boolean;
	failure: Failure | null;
	/** Lines whose citations moved to make room, by their *new* number. Empty for
	 *  an appended line, which displaces nothing. */
	renumbered: number[];
	applied: boolean;
	valid: boolean | null;
	holes: number[];
	only_holes: boolean;
	/** The opener of the subproof this line landed in, null at the proof root.
	 *  Read off the *checked* proof rather than echoed from the request, because
	 *  indentation is what places a line. */
	scope: number | null;
	/** The kind of scope this line opens, if it opens one. */
	opens_scope: string | null;
}

/** Take a line back out, closing the gap its number leaves. Mirrors
 *  `LineRemoval`.
 *
 *  The inverse of `LineProposal`, and what a caller working top-down needs to
 *  undo a step it has decided against. A line another line *cites* is refused
 *  rather than removed: its dependents would lose their justification, and there
 *  is no answer to give them. A dry run unless `apply` is set. */
export interface LineRemoval {
	line: number;
	apply?: boolean;
}

/** What removing a line would do, or did. Mirrors `LineRemovalOutcome`. */
export interface LineRemovalOutcome {
	line: number;
	/** The line as it stood, so a caller can put it back without having kept it. */
	removed: string;
	/** Lines whose citations moved up to close the gap, by their *new* number. */
	renumbered: number[];
	applied: boolean;
	valid: boolean | null;
	holes: number[];
	only_holes: boolean;
}

/** One edge below a term node: the slot it fills, and what sits there. */
export interface TermChild {
	slot: string;
	id: string;
}

/** One node of a term subgraph. Mirrors `TermNodeOut` in app/schemas.py.
 *
 *  `rendered` is this node read through the requested notation, so a caller has
 *  the projection *and* the identity of every subterm at once — it can point at a
 *  formula's part by `id` without restating it, which a rendered string alone
 *  cannot support.
 *
 *  `truncated` means the walk stopped here with children still below: a horizon,
 *  not a leaf. `children` is reported either way, so a deeper request can be
 *  aimed rather than repeated. */
export interface TermNode {
	id: string;
	kind: string;
	constructor: string | null;
	literal: string | null;
	sort: string | null;
	var_name: string | null;
	bound_index: number | null;
	digest: string | null;
	alpha_digest: string | null;
	/** How far below the requested root this node sits. A node reachable by two
	 *  paths is reported once, at the shallower of them. */
	depth: number;
	children: TermChild[];
	rendered: string | null;
	truncated: boolean;
}

/** One theorem whose conclusion could be a goal — a candidate, not an answer.
 *  Mirrors `TheoremCandidate`.
 *
 *  `exact` says the conclusion *is* the goal up to a consistent renaming of its
 *  variables, so citing it needs no instantiation. `premise_count` is what to
 *  rank by after that: a theorem with none can close the goal on its own. */
export interface TheoremCandidate {
	label: string;
	formal_system_id: string;
	/** The interned root of the conclusion — pass to `systems.term` to walk the
	 *  structure instead of reparsing `statement`. Identity and reading together. */
	statement_term_id: string;
	statement: string;
	primitive: boolean;
	premise_count: number;
	exact: boolean;
}

/** What could conclude a goal, narrowed by the shape of its conclusion.
 *  Mirrors `TheoremMatches`.
 *
 *  A filter's output, deliberately not a verdict: every candidate still has to
 *  unify, and this endpoint does not build the system to find out — the citation
 *  search on a proof line does. `unindexed` is what the filter could not see
 *  (theorems with no cached conclusion term), because a short list is otherwise
 *  indistinguishable from a complete one. */
export interface TheoremMatches {
	formal_system_id: string;
	term_id: string;
	/** The goal's root production, which is what was filtered on. */
	constructor: string;
	candidates: TheoremCandidate[];
	/** How many matched before `limit` cut the list. */
	matched: number;
	truncated: boolean;
	unindexed: number;
	/** Entries in layers this filter cannot ask about at all — an edge that
	 *  restates what it carries, or one whose rename leaves this system's
	 *  production without a pre-image there. */
	unfiltered: number;
}

/** A justification that checks, in `CitationProposal`'s own shape so acting on
 *  one is a copy rather than a translation. Mirrors `CitationSuggestion`. */
export interface CitationSuggestion {
	rule: string;
	antecedents: number[];
	/** The reference text this formats to, e.g. `"MP, 1, 2"`. */
	citation: string;
	/** Whether it is one of the system's own rules or an entry from its library —
	 *  where it came from, not how it was checked. */
	source: 'rule' | 'theorem';
	/** Whether the cited line is a subproof opener rather than an antecedent. */
	discharge: boolean;
	exact: boolean;
	/** Whether this rule justifies *any* line (a hypothesis rule). True, and a
	 *  fact about the system rather than about this goal — so it is reported and
	 *  ranked last rather than dropped. */
	assumption: boolean;
}

/** Justifications found for one line, and how much was looked at.
 *  Mirrors `CitationSearch`.
 *
 *  The move the loop was missing: a failure says which premise is missing and a
 *  hole says what is left to prove, and this says *what to cite* — as proposals
 *  already checked against the lines that stand above the goal. */
export interface CitationSearch {
	line: number;
	suggestions: CitationSuggestion[];
	rules_tried: number;
	candidates_tried: number;
	/** Library entries the prefilter could not reach (no cached conclusion term). */
	unindexed: number;
	/** Library entries in a layer the prefilter cannot ask about at all; see
	 *  `TheoremMatches.unfiltered`. */
	unfiltered: number;
	/** Whether anything was cut: more justifications were found than `limit`, or
	 *  the prefilter matched more candidates than it was allowed to offer. */
	truncated: boolean;
}

/** A term's subgraph: every node once, edges by id. Mirrors `TermGraphOut`. */
export interface TermGraph {
	root: string;
	formal_system_id: string;
	notation: string | null;
	nodes: TermNode[];
	truncated: boolean;
}

/** The authenticated user — mirrors `UserRead` in app/auth/schemas.py. */
export interface User {
	id: string;
	email: string;
	is_active: boolean;
	is_superuser: boolean;
	is_verified: boolean;
	display_name: string | null;
}

// ---------------------------------------------------------------------------
// Formal-system objects (CRUD) — mirror the read/write models in app/schemas.py.
// Read models carry each part's `id` so a client can address it for edit/delete;
// write models set only the fields the corresponding endpoint accepts.
// ---------------------------------------------------------------------------

/** A typed variable slot, e.g. `s : term`. */
export interface Binding {
	var: string;
	sort: string;
}

/** A production's slot, which — unlike a rule's or a definition's metavariable —
 * may *bind*. `scopes_over` names the sibling slots its binding reaches into:
 * `["phi"]` for the `x` of `∀x.phi`, empty for an ordinary argument slot.
 * Declared, not inferred, and what lets a definition's `fresh` clause be read off
 * the grammar instead of written by hand. */
export interface ProductionBinding extends Binding {
	/** Optional on the way in — omitted means "binds nothing", which is what a
	 * slot says unless declared otherwise. Always present on the way out. */
	scopes_over?: string[];
}

export interface BracketPair {
	id: string;
	opening: string;
	closing: string;
}

export interface Sort {
	id: string;
	name: string;
}

export interface Production {
	id: string;
	name: string;
	sort: string;
	kind: string;
	template: string | null;
	regex: string | null;
	/** kind==="atom": the constant's literal token. */
	atom_value: string | null;
	/** kind==="atom": the indexed family's base (e.g. `p` for the `p_#` family). */
	atom_base: string | null;
	/** Whether this production's tokens are constants of the object language
	 * (`⊥`, `∅`) rather than variables of it. Declared, not inferred — `⊥` in
	 * `formula ::= ⊥` and `a` in `setvar ::= a | b | c` are the same shape and
	 * opposite answers. Only a constant may appear in a definition's defining
	 * form without the defined form supplying it. */
	denotes_constant: boolean;
	bindings: ProductionBinding[];
}

export interface LinePart {
	id: string;
	name: string;
	regex: string;
}

/** The subproof scope a line type opens, or null for a plain line. */
export type LineScope = 'assumption' | 'variable';
/** What the checker does with a line: assert-and-justify, or prose it ignores. */
export type LineBehaviour = 'logical' | 'comment';

export interface LineType {
	id: string;
	name: string;
	shape: string;
	logical_sort: string | null;
	scope: LineScope | null;
	behaviour: LineBehaviour;
	parts: LinePart[];
}

/** A definition's proof obligation, discharged by citing a settled statement.
 *
 * Some definitions hold only because something is *provable* — the choice of a
 * dummy variable being immaterial, say. That is a claim about derivability rather
 * than about the shape of a term, so it is not a proviso: it is settled once,
 * when the system is built, by naming a theorem or premise-free rule whose
 * statement is the obligation. Both halves travel together. */
export interface Justification {
	/** The label of the rule or theorem cited. */
	label: string;
	/** The obligation, in the system's own grammar, over the definition's own
	 * metavariables. */
	statement: string;
}

export interface Definition {
	id: string;
	sort: string;
	name: string;
	higher: string;
	lower: string;
	/** Soundness provisos, one kernel-vocabulary line each (implicit conjunction),
	 * mirroring a rule's `side_conditions`. */
	provisos: string[];
	bindings: Binding[];
	/** The defining form's bound variables (the `fresh` clause). Declaring them
	 * lets a quantified definition take the kernel path so its proviso is enforced. */
	fresh: Binding[];
	/** Optional name a proof cites this definition by (`[<label>, <line>]`); null
	 * when unnamed. Unique within a system. */
	label: string | null;
	/** The obligation this definition holds only under, or null — which is nearly
	 * all of them. */
	justification: Justification | null;
}

export interface Axiom {
	id: string;
	label: string;
	name: string;
	formula: string;
	bindings: Binding[];
}

/**
 * How a rule justifies a step: `structural` (first-order term unification, the
 * default — logical systems) or `string` (associative matching for a
 * string-rewriting system such as MIU, whose rules split/concatenate strings).
 */
export type RuleMatching = 'structural' | 'string';

/**
 * The subproof a discharge rule (→I, RAA, ∀I) consumes: `derive` is the pattern
 * its final line must match, opened by exactly one of `assume` (a hypothesis) or
 * `fresh` (an eigenvariable). Mirrors the engine's `SubproofSchema`.
 */
export interface Subproof {
	derive: string;
	assume: string | null;
	fresh: string | null;
}

export interface Rule {
	id: string;
	label: string;
	name: string;
	deduction: string;
	antecedents: string[];
	bindings: Binding[];
	/** Soundness provisos, one kernel-vocabulary line each (implicit conjunction). */
	side_conditions: string[];
	matching: RuleMatching;
	/** The subproof a discharge rule consumes, or null for a line-antecedent rule. */
	subproof: Subproof | null;
	/** Whether a citation may name more lines than the rule has antecedent slots;
	 * the surplus is kept unconstrained. False means an exact citation. */
	allow_extra_antecedents: boolean;
}

/** The public face of a system's owner (never email) — mirrors `SystemOwner`. */
export interface SystemOwner {
	id: string;
	display_name: string | null;
}

/** List-row view of a system. `published_at` non-null ⇒ public/published. */
export interface FormalSystemSummary {
	id: string;
	name: string;
	slug: string;
	description: string | null;
	/** Where the system came from, when it was not authored here — an import's
	 * own sentence, recorded once per corpus rather than on each of its proofs. */
	provenance: string | null;
	inherits_from_id: string | null;
	published_at: string | null;
	created_at: string;
	updated_at: string;
	owner: SystemOwner | null;
}

/** Full system aggregate. Note the line-types collection is keyed `lines`. */
export interface FormalSystemDetail extends FormalSystemSummary {
	brackets: BracketPair[];
	/** Whether the system writes every token whitespace-separated. */
	token_separated: boolean;
	sorts: Sort[];
	productions: Production[];
	lines: LineType[];
	definitions: Definition[];
	axioms: Axiom[];
	rules: Rule[];
	/** Named notations this system's terms may be *read* through, as against the
	 * grammar they are written in. Names only — the templates never leave the
	 * server; a client asks for a rendering by passing one to `proofs.structure`. */
	notations: string[];
}

/** One bound variable of a definition's defining form, as the engine reads it.
 * `inferred` is false when the author wrote it in the `fresh` clause and true
 * when the engine read it off the grammar's binding slots — reported because
 * inference is otherwise silent. */
export interface DefinitionBinder {
	var: string;
	sort: string;
	inferred: boolean;
}

export interface DefinitionBinders {
	/** The stored definition this reports on. Neither `label` nor `defined_form`
	 * identifies a row — a definition may be unnamed, two may share one defined
	 * form, and one whose defining form matched nothing is dropped at build — so
	 * join on this, not on position. */
	definition_id: string;
	label: string | null;
	/** For display, not identification. */
	defined_form: string;
	binders: DefinitionBinder[];
}

export interface SystemValidation {
	success: boolean;
	errors: string[];
	system_name: string | null;
	line_type_count: number | null;
	inference_rule_count: number | null;
	/** Per compiled definition, the `fresh` clause the engine settled on. Only
	 * definitions that *layer* appear — one whose defining form matched nothing is
	 * dropped at build. Empty when the system did not compile. */
	definitions: DefinitionBinders[];
}

// --- Write payloads --------------------------------------------------------

export interface FormalSystemCreate {
	name: string;
	description?: string | null;
	inherits_from_id?: string | null;
}

export interface FormalSystemUpdate {
	name?: string;
	description?: string | null;
	inherits_from_id?: string | null;
	/** true → publish (public), false → unpublish (draft), omitted → unchanged. */
	published?: boolean;
	/** See declarative.SystemSpec.token_separated. */
	token_separated?: boolean;
}

// --- Relations between systems (the general edge) ---------------------------

/** What an edge claims: `extension` contains the source, `interpretation` translates it. */
export type RelationKind = 'extension' | 'interpretation';
/** `draft` transfers nothing; `discharged` is what makes a citation resolve. */
export type RelationStatus = 'draft' | 'discharged';

/** One entry of an edge's sort or symbol map — grammar *names*, since the two
 * systems' namespaces are separate and there is no id to share. */
export interface SystemRelationRename {
	source: string;
	target: string;
}

/** One metavariable the statement template introduces — `Γ : context`. The sort
 * names one of the *target's* sorts, since that is the grammar the template is
 * read against. Not a rename of anything: a sequent's antecedent has no
 * counterpart in the Hilbert formula being wrapped. */
export interface SystemRelationExtra {
	name: string;
	sort: string;
}

export interface SystemRelationObligationInput {
	source_label: string;
	/** A rule of this system, or a theorem it has proved — one or the other. */
	discharged_by_primitive?: string | null;
	discharged_by_theorem_id?: string | null;
	status?: RelationStatus;
}

export interface SystemRelationObligation extends SystemRelationObligationInput {
	id: string;
}

export interface SystemRelationCreate {
	source_system_id: string;
	kind?: RelationKind;
	status?: RelationStatus;
	/** How this system restates a transferred theorem when it states a different
	 * *kind* of thing than the source does — `'G ⊢ {wff}'`, whose one
	 * brace-marked hole names the sort the transferred statement is read at
	 * here. Absent between two systems that agree what a judgement is. */
	statement_template?: string | null;
	sorts?: SystemRelationRename[];
	symbols?: SystemRelationRename[];
	extras?: SystemRelationExtra[];
	obligations?: SystemRelationObligationInput[];
}

/** A partial edit; a collection given is replaced whole. The source is not
 * editable — repointing an edge is a different relationship with different
 * obligations, so delete and create. */
export interface SystemRelationUpdate {
	kind?: RelationKind;
	status?: RelationStatus;
	/** Which edge wins a label two of them offer; lower first. */
	position?: number;
	/** The empty string clears the wrap; omitting it leaves it alone. */
	statement_template?: string | null;
	sorts?: SystemRelationRename[];
	symbols?: SystemRelationRename[];
	extras?: SystemRelationExtra[];
	obligations?: SystemRelationObligationInput[];
}

export interface SystemRelation {
	id: string;
	source_system_id: string;
	source_system_name: string;
	target_system_id: string;
	kind: RelationKind;
	status: RelationStatus;
	position: number;
	statement_template: string | null;
	sorts: SystemRelationRename[];
	symbols: SystemRelationRename[];
	extras: SystemRelationExtra[];
	obligations: SystemRelationObligation[];
	/** Whether this edge transfers anything today, and which obligations stop it. */
	resolves: boolean;
	outstanding: string[];
}

export interface BracketCreate {
	opening: string;
	closing: string;
}
export type BracketUpdate = Partial<BracketCreate>;

export interface SortCreate {
	name: string;
}
export type SortUpdate = Partial<SortCreate>;

export interface ProductionCreate {
	name: string;
	sort: string;
	/** Exactly one of `template` / `regex` / `atom_value` / `atom_base` is required
	 * by the backend — a composite, a leaf regex, an atom constant, or an atom
	 * family respectively. */
	template?: string | null;
	regex?: string | null;
	atom_value?: string | null;
	atom_base?: string | null;
	/** See `Production.denotes_constant`. Omitted means variable-like. */
	denotes_constant?: boolean;
	bindings?: ProductionBinding[];
}
export type ProductionUpdate = Partial<ProductionCreate>;

export interface LinePartInput {
	name: string;
	regex: string;
}

export interface LineTypeCreate {
	name: string;
	shape: string;
	logical_sort?: string | null;
	scope?: LineScope | null;
	behaviour?: LineBehaviour;
	parts?: LinePartInput[];
}
export type LineTypeUpdate = Partial<LineTypeCreate>;

export interface DefinitionCreate {
	sort: string;
	name: string;
	higher: string;
	lower: string;
	/** Soundness provisos, one kernel-vocabulary line each (implicit conjunction),
	 * mirroring rules' `side_conditions`. */
	provisos?: string[];
	bindings?: Binding[];
	/** The defining form's bound variables (the `fresh` clause). */
	fresh?: Binding[];
	/** Optional citation name (`[<label>, <line>]`); must be unique within a system. */
	label?: string | null;
}
export type DefinitionUpdate = Partial<DefinitionCreate>;

export interface AxiomCreate {
	label: string;
	name: string;
	formula: string;
	bindings?: Binding[];
}
export type AxiomUpdate = Partial<AxiomCreate>;

export interface RuleCreate {
	label: string;
	name: string;
	deduction: string;
	antecedents?: string[];
	bindings?: Binding[];
	side_conditions?: string[];
	matching?: RuleMatching;
	subproof?: Subproof | null;
	allow_extra_antecedents?: boolean;
}
export type RuleUpdate = Partial<RuleCreate>;

// ---------------------------------------------------------------------------
// Proofs (stored CRUD) — mirror the read/write models in app/schemas.py. A proof
// belongs to a formal system, carries its proof text (lines written in that
// system's own grammar), and is verified against it on demand (the verdict is
// cached in `valid` / `result`).
// ---------------------------------------------------------------------------

/** List-row view of a proof. `published_at` non-null ⇒ public/published. */
export interface ProofSummary {
	id: string;
	name: string;
	slug: string;
	/** A human sentence beside `name`, which is the proof's identity. The two
	 * coincide for a hand-authored proof and part ways on an import, where `name`
	 * is the Metamath label a citation must spell (`sqrt2irr`) and this is what the
	 * file's comment opens with. */
	title: string | null;
	description: string | null;
	formal_system_id: string;
	folder_id: string | null;
	/** Last-known validity; null until the proof has been verified. */
	valid: boolean | null;
	published_at: string | null;
	created_at: string;
	updated_at: string;
	owner: SystemOwner | null;
}

/** One outgoing reference edge, read back — mirrors `ProofReferenceOut`. */
export interface ProofReference {
	referenced_proof_id: string;
	/** The label this proof cites the lemma by in its source (`[alias.line]`). */
	alias: string;
	name: string;
	slug: string;
	published: boolean;
}

/** One incoming reference edge, read back — mirrors `ProofReferrerOut`. The
 * "used by" direction: a proof that cites this one as a lemma. */
export interface ProofReferrer {
	proof_id: string;
	/** The label the referring proof cites this one by (`[alias.line]`). */
	alias: string;
	name: string;
	published: boolean;
}

/** One outgoing reference edge, as submitted — mirrors `ProofReferenceInput`. */
export interface ProofReferenceInput {
	referenced_proof_id: string;
	alias: string;
}

/** A citable library entry — mirrors `PromotedTheoremOut`.
 *
 * `statement` is the conclusion's kernel term rendered, not the source line the
 * author typed: promotion takes the term the check ran on. `proved_by_id` is
 * null for an entry that arrived with a corpus import, which no proof here may
 * retire. */
export interface PromotedTheorem {
	id: string;
	label: string;
	statement: string;
	formal_system_id: string;
	proved_by_id: string | null;
	/** Assumptions this entry transitively rests on, by label. Non-empty means it
	 * is a *conditional* result: citable, and resting on something nobody has
	 * proved. Never leave it out of a display that says the entry stands. */
	assumes: string[];
	/** Whether promoting this *discharged* an assumption of the same label —
	 * replaced a debt with its warrant. Worth surfacing because it is not what
	 * the caller asked for: it asked to promote, and the label happening to name
	 * an assumption is what turned that into paying one off. */
	discharged: boolean;
}

/** A statement named structurally, before there is a proof to put it in —
 * mirrors `StatementProposal`.
 *
 * A dry run unless `store`: asking whether something is proved is a question,
 * and a question does not write rows. `store` interns the term and hands back an
 * id — which is what makes it usable as a `ref` elsewhere — and is the owner's. */
export interface StatementProposal {
	statement: TermProposal;
	store?: boolean;
	limit?: number;
}

/** A resolved statement and what could conclude it — mirrors `StatementOutcome`.
 *
 * `rendered` is the system's own source spelling, exact by construction: a
 * production's render steps *are* its source template. `term_id` is present only
 * when `store` was set.
 *
 * `matches` are **candidates, never a verdict**, `exact` ones included: that flag
 * is a ranking hint, and confirming that one really proves the statement is
 * unification against a line in a real scope (`proofs.citations`). Nothing here
 * says "proved" — do not add a UI that does. `exact_is_approximate` warns that
 * this system's grammar makes the flag over-report; `unindexed` and `unfiltered`
 * are what the filter could not see, and a UI hiding any of the three turns a
 * short list into a complete-looking one. */
export interface StatementOutcome {
	formal_system_id: string;
	term_id: string | null;
	rendered: string;
	constructor: string | null;
	digest: string;
	alpha_digest: string;
	matches: TheoremCandidate[];
	matched: number;
	truncated: boolean;
	unindexed: number;
	unfiltered: number;
	exact_is_approximate: boolean;
}

/** An external work something here claims to formalize — mirrors
 * `SourceDocumentCreate`. `version` is part of the document's identity, not a
 * note about it. */
export interface SourceDocumentCreate {
	kind: 'arxiv' | 'doi' | 'isbn' | 'url' | 'other';
	identifier: string;
	version?: string;
	title?: string | null;
	url?: string | null;
	content_hash?: string | null;
	licence?: string | null;
	retrieved_at?: string | null;
}

export interface SourceDocument extends SourceDocumentCreate {
	id: string;
	created_at: string;
	/** How many claims point at this document. */
	formalizations: number;
}

/** One of the paper's notions and what it was read as — mirrors
 * `GlossaryEntryInput`. At least one of `label` and `term_id`: an entry naming
 * nothing records only that somebody thought about the word. */
export interface GlossaryEntryInput {
	notion: string;
	label?: string | null;
	term_id?: string | null;
	reasoning?: string | null;
}

export interface GlossaryEntry extends GlossaryEntryInput {
	id: string;
}

/** Claim that a term formalizes a result — mirrors `FormalizationCreate`.
 *
 * `reasoning` is required and is the point: a claim with no argument is a tick.
 * `attested_as` names the agent where that was not a person — a model identifier
 * — recorded *beside* the account rather than instead of it. */
export interface FormalizationCreate {
	document_id: string;
	claim: string;
	informal_statement: string;
	formal_system_id: string;
	statement_term_id: string;
	proof_id?: string | null;
	reasoning: string;
	attested_as?: string | null;
	glossary?: GlossaryEntryInput[];
}

/** A second reader's verdict — mirrors `FormalizationReview`. `disputed`
 * requires a note, since a dispute nobody explained is not a finding. */
export interface FormalizationReview {
	verdict: 'confirmed' | 'disputed';
	note?: string | null;
}

/** One claim, read back — mirrors `Formalization`.
 *
 * The formal side is `statement_term_id` rather than a rendering: read it with
 * `systems.term(...)`, which renders a stored term through a chosen notation and
 * carries every subterm's id. `review_verdict` is null until somebody who is not
 * the attestor has said something — an unreviewed claim is the ordinary state
 * and a UI should let it look like one rather than hiding it. */
export interface Formalization {
	id: string;
	document: SourceDocument;
	claim: string;
	informal_statement: string;
	formal_system_id: string;
	statement_term_id: string;
	proof_id: string | null;
	reasoning: string;
	attested_by: SystemOwner | null;
	attested_as: string | null;
	attested_at: string;
	review_verdict: 'confirmed' | 'disputed' | null;
	review_note: string | null;
	reviewed_by: SystemOwner | null;
	reviewed_at: string | null;
	glossary: GlossaryEntry[];
}

/** A citable statement nobody has proved — mirrors `AssumptionOut`.
 *
 * `dependents` counts the library entries that rest on it **transitively**, so
 * an entry three hops away naming it nowhere still counts. That is the ranking
 * the public register uses: it says which gap closing pays for most. */
export interface Assumption {
	id: string;
	label: string;
	statement: string;
	reason: string;
	source: string | null;
	formal_system_id: string;
	formal_system_name: string;
	dependents: number;
	created_at: string;
}

/** The same, with the entries resting on it named — mirrors `AssumptionDetail`. */
export interface AssumptionDetail extends Assumption {
	dependent_labels: string[];
}

/** Take a statement on as citable without proving it — mirrors `AssumptionCreate`.
 *
 * `statement` is source text in the system's own grammar, as an imported
 * theorem's is. `reason` is required: an assumption with no reason is an axiom
 * nobody remembers adopting. */
export interface AssumptionCreate {
	label: string;
	statement: string;
	premises?: string[];
	metavariables?: Record<string, string>;
	distinct?: string[];
	reason: string;
	source?: string | null;
}

/** One assumption as a dependency report names it — mirrors `AssumedOut`. */
export interface Assumed {
	theorem_id: string;
	formal_system_id: string;
	label: string;
	statement: string;
	reason: string;
	source: string | null;
}

/** What a proof rests on that nobody has proved — mirrors `ProofProvenance`.
 *
 * `complete` is the honest half, and there are two ways to lose it:
 * `unresolved` names cited labels the report could not account for, and
 * `unread_lemmas` names cited lemma proofs holding no stored structure. A UI
 * showing `assumes` without them would present a partial answer as a whole one. */
export interface ProofProvenance {
	proof_id: string;
	assumes: Assumed[];
	unresolved: string[];
	unread_lemmas: string[];
	complete: boolean;
}

export interface ProofDetail extends ProofSummary {
	source: string;
	/** Cached `proof.data()` from the last verification (null = never run). */
	result: ProofData | null;
	/** Outgoing references (lemmas this proof cites), filtered to those the
	 * viewer may read. */
	references: ProofReference[];
	/** Incoming references (proofs that cite this one as a lemma), filtered to
	 * those the viewer may read. */
	referenced_by: ProofReferrer[];
	/** The library entry this proof establishes, null until it is promoted. */
	theorem: PromotedTheorem | null;
	/** What the *system* records about this proof's label — the corpus's own
	 * documentation, authorship included, as against `title`/`description`, which
	 * are the proof's and are editable. Null for every hand-authored proof. */
	documentation: LabelDescription | null;
}

/** One `(Contributed by NM, 5-Apr-1994.)` clause, as its three parts. Every field
 * verbatim: `kind` is an open set and `dated` is a string, because the corpus
 * misspells four kinds and malforms 22 dates, and normalising either would mean
 * deciding what an upstream typo meant. */
export interface Attribution {
	kind: string;
	who: string;
	dated: string;
}

/** What a system says about one of the labels it names — a production, a
 * definition, a primitive theorem or a proof alike. `title` is the prose's first
 * sentence, which is a title in all but name: Metamath declares none. */
export interface LabelDescription {
	label: string;
	title: string | null;
	text: string;
	attributions: Attribution[];
	/** Where this prose points, in order of appearance. */
	references: LabelReference[];
	/** And what points back — capped; `mentioned_by_total` is the real number. */
	mentioned_by: LabelMention[];
	mentioned_by_total: number;
	/** `(New usage is discouraged.)` — the statement exists, do not build on it. */
	discouraged_usage: boolean;
	/** `(Proof modification is discouraged.)` — the proof is as it is on purpose. */
	discouraged_modification: boolean;
	/** What the corpus declares this proof does *without* — set.mm's `$j usage …
	 *  avoids …`, its record that a theorem is derivable from less. The file's
	 *  claim; nothing re-derives the proof's dependencies to check it. */
	avoids: string[];
}

/** One label a prose search matched, and where in it the words landed.
 *
 * The listing shape beside `LabelDescription`'s single-label one: a title, a
 * slice of the prose, and enough to follow the hit. The full record — the
 * attributions, the cross-references, what points back — is one `label()` call
 * away, and a search that carried it would ship a corpus comment and its whole
 * reference graph per row. */
export interface LabelHit {
	label: string;
	/** The layer the label lives on, which on a layered corpus is not the system
	 * that was searched — so it is what a follow-up `label()` must be addressed to. */
	formal_system_id: string;
	title: string | null;
	/** The prose around the first matched word, ellipsed where it is a slice. Null
	 * when no word landed in the body — always so for a `label` or `title` match,
	 * and possible for a `record` one, whose words are spread across fields. */
	excerpt: string | null;
	/** The tightest single field holding *every* word, or `record` when no one
	 * field holds them all. Served because a ranking a caller cannot account for
	 * is one it has to trust blindly or ignore. */
	matched: 'label' | 'title' | 'text' | 'record';
	/** Set when the label names a proof the viewer may open — null for the roughly
	 * half of a corpus's labels that are `$a`s and have no proof at all. */
	proof_id: string | null;
	proof_title: string | null;
	discouraged_usage: boolean;
	discouraged_modification: boolean;
}

/** A page of prose hits, how much prose there was to miss, and what was asked.
 *
 * `documented` is what makes an empty result readable: "the words are not in this
 * corpus" and "this corpus is undocumented" are the same empty list otherwise,
 * and only one of them means the search is finished.
 *
 * `searched` is the words actually used — lowercased, deduplicated, and capped.
 * Every one of them appears in every hit, so a query past the cap is answered
 * more broadly than it was asked; this is what keeps that visible. */
export interface LabelSearch extends Page<LabelHit> {
	documented: number;
	searched: string[];
}

/** One `~ target` the prose points at, and the span of `text` it occupies.
 *
 * `start`/`end` are why this needs no parser here: the markup rule is Metamath's,
 * it lives in the engine, and the renderer slices the prose at these offsets. See
 * `renderProse` in `$lib/prose`.
 *
 * `proof_id` is set when the target names a proof of this system the viewer may
 * open — null for a URL, for a label that is a definition or an axiom rather than
 * a proof, and for a target that resolves to nothing. */
export interface LabelReference {
	target: string;
	start: number;
	end: number;
	proof_id: string | null;
	title: string | null;
}

/** A label whose prose points at the one being read — a reference, backwards. */
export interface LabelMention {
	label: string;
	proof_id: string | null;
	title: string | null;
}

/** One theorem a proof cites, or one proof that cites it — mirrors
 * `TheoremCitation`. `proof_id` is null when the label has no proof of its own
 * (half a corpus's labels are primitives) or belongs to a draft. */
export interface TheoremCitation {
	label: string;
	proof_id: string | null;
	title: string | null;
}

/** A proof's place in its corpus's citation graph. Distinct from
 * `ProofDetail.references`/`referenced_by`, which are the alias-lemma edges a
 * hand-authored proof declares: these are citations of *theorems*, resolved
 * through the library by label, and are what an imported corpus is made of. */
export interface ProofCitations {
	cites: TheoremCitation[];
	/** Capped — `cited_by_total` says how many there really are. */
	cited_by: TheoremCitation[];
	cited_by_total: number;
}

// The stored structure of a checked proof — mirrors the ProofStructure models in
// app/schemas.py, which read the rows in app/db/proof_lines.py. Distinct from
// `ProofDetail.result`: that is the display snapshot the editor renders, this is
// the structure the checker derived (each formula a node in the system's term
// graph, each justification an edge).

/** A term-graph node's identity, without its children. `digest` matches exactly;
 * `alpha_digest` matches up to consistent renaming of free variables. */
export interface TermSummary {
	id: string;
	kind: string;
	constructor: string | null;
	literal: string | null;
	sort: string | null;
	digest: string;
	alpha_digest: string | null;
}

/** One justification edge. Exactly one target form is populated: `line_id` for a
 * citation within this proof, or `proof_id`/`number` for one reaching into a
 * cited lemma. */
export interface ProofStructureAntecedent {
	/** 'antecedent' (a declared rule slot), 'extra' (a tolerated surplus line),
	 * or 'subproof' (the opener of a block a discharge rule consumed). */
	role: string;
	position: number;
	line_id: string | null;
	proof_id: string | null;
	number: number | null;
}

export interface ProofStructureLine {
	id: string;
	/** Index into the source's lines, blanks and commentary included — unlike
	 * `number`, the citation number, which is null for those. */
	position: number;
	number: number | null;
	indent: number;
	display: string;
	line_type: string | null;
	behaviour: string | null;
	label: string | null;
	/** The citation as written, then the rule the checker resolved it to (null
	 * when nothing justified the line: a scope opener, axiom, or definitional step). */
	reference: string | null;
	rule: string | null;
	/** The definition a definitional step applied. A generic `[Def, n]` citation
	 * names none, so this is the only record of which one it was. */
	definition_id: string | null;
	valid: boolean;
	invalid_message: string | null;
	/** The same verdict as data; `code === 'hole'` is an open goal. */
	failure: Failure | null;
	warning_message: string | null;
	/** The scope this line opens, and the opener of the subproof it sits in. */
	opens_scope: string | null;
	scope_id: string | null;
	/** The line's formula in the term graph; null for a line that bears none. */
	term: TermSummary | null;
	/** The line's formula re-spelled in the requested notation, or null when none
	 * was asked for. Narrower than `display` twice over: that is the whole
	 * authored line, this is the term alone — so a client showing a notation
	 * writes the citation itself, from `reference`. */
	rendered: string | null;
	antecedents: ProofStructureAntecedent[];
}

/** What a citation's label names, read from rows alone — the cheap half of a
 * `LineJustification`. That record re-checks the proof (the substitution it
 * reports is derived), which is why it is signed-in only; this is what a citation
 * *says*, and is a handful of row reads, so any reader of the system gets it. */
export interface LibraryEntry {
	label: string;
	/** The rule's own name where it has one; empty for a library entry, which is
	 * named by its label alone. */
	name: string;
	/** 'rule' (a primitive this system declares), 'axiom' or 'theorem'. */
	kind: string;
	conclusion: string;
	premises: string[];
	discharges: string | null;
	title: string | null;
	proof_id: string | null;
	/** The notation the schemas were read through, echoed as `ProofStructure`
	 * echoes it: a client showing a proof in one spelling must be able to tell a
	 * served rendering from a silently ignored request. */
	notation: string | null;
}

/** One antecedent of the rule, and the line that filled it. `schema_form` is the
 * rule's own — what it demands of the slot — and empty for a surplus line an
 * `allow_extra_antecedents` rule tolerated, which fills none. */
export interface JustifyingPremise {
	position: number;
	schema_form: string;
	number: number | null;
	statement: string | null;
	extra: boolean;
}

/** What one of the rule's metavariables stood for on this step. */
export interface JustifyingAssignment {
	variable: string;
	stands_for: string;
}

/** A side-condition the step had to satisfy, in the author's own words, and the
 * metavariables it mentions — which is how a reader finds it among the
 * assignments and sees what it was actually about. */
export interface JustifyingProviso {
	source: string;
	variables: string[];
}

/** Why one line follows, as a reader can check it.
 *
 * `Failure` says why a line did *not* check; this is the other half, and the
 * citation on the line was all a reader had of it. */
export interface LineJustification {
	line: number;
	citation: string | null;
	/** 'rule' — an inference rule or a promoted theorem, which are one shape to
	 * the checker — or 'definition' for a definitional step, which cites neither. */
	kind: string;
	label: string;
	name: string;
	conclusion: string;
	premises: JustifyingPremise[];
	assignments: JustifyingAssignment[];
	provisos: JustifyingProviso[];
	/** The subproof a discharge rule consumed, as its schema reads. */
	discharges: string | null;
	/** The corpus's own one-line summary of the cited label, where it has one. */
	title: string | null;
	/** The proof establishing the cited theorem, when the viewer may read it. */
	proof_id: string | null;
	notation: string | null;
}

export interface ProofStructure {
	proof_id: string;
	/** Whether a structure is materialised. Never "derived nothing" (an empty
	 * proof still stores its one blank line), but not quite "unchecked" either: a
	 * proof checked before this store existed materialises on its next verify.
	 * Read `ProofSummary.valid` for whether it was checked. */
	stored: boolean;
	/** The notation the lines were rendered through, echoed back; null when none
	 * was asked for. A name the system does not store is a 404, not a null. */
	notation: string | null;
	lines: ProofStructureLine[];
}

/** One node of a system's folder tree, with everything under it.
 *
 * An imported corpus fills this from the section headers its `.mm` file draws
 * (`####` part, `#*#*` section, `=-=-` subsection, `-.-.` subsubsection): the
 * depth *is* the nesting, so there is no level field — it is where the node sits.
 * `description` is the prose a header carries after its title.
 *
 * `proofs` counts what sits directly in this folder, not in the whole subtree: a
 * corpus's part-level node holds nothing itself and thousands beneath it. */
export interface Folder {
	id: string;
	name: string;
	slug: string;
	description: string | null;
	position: number;
	proofs: number;
	children: Folder[];
}

export interface ProofCreate {
	name: string;
	formal_system_id: string;
	title?: string | null;
	description?: string | null;
	source?: string;
}

export interface ProofUpdate {
	name?: string;
	/** null clears it; omitted leaves it unchanged. */
	title?: string | null;
	description?: string | null;
	source?: string;
	/** true → publish (public), false → unpublish (draft), omitted → unchanged. */
	published?: boolean;
}

// ---------------------------------------------------------------------------
// Server-side pagination — mirrors `Page[T]` in app/schemas.py. The list
// endpoints return one page (`items`) plus the full `total` matching the query,
// so a client can drive page controls without a second request.
// ---------------------------------------------------------------------------

export interface Page<T> {
	items: T[];
	total: number;
	limit: number;
	offset: number;
}

/** Query params shared by the paginated list endpoints. */
export interface ListParams {
	/** Page size (1–100). */
	limit?: number;
	/** Row offset of the page's first item. */
	offset?: number;
	/** Case-insensitive filter over name/description. */
	search?: string;
	/** Column id to sort by: name | description | author | created_at | updated_at. */
	sort?: string;
	/** Descending when true, ascending otherwise. */
	desc?: boolean;
}

/** Serialise `ListParams` (plus any extras) into a `?a=b&…` string. */
function listQuery(
	params: ListParams = {},
	extra: Record<string, string | undefined> = {}
): string {
	const q = new URLSearchParams();
	if (params.limit != null) q.set('limit', String(params.limit));
	if (params.offset != null) q.set('offset', String(params.offset));
	if (params.search) q.set('search', params.search);
	if (params.sort) q.set('sort', params.sort);
	if (params.desc) q.set('desc', 'true');
	for (const [key, value] of Object.entries(extra)) {
		if (value != null) q.set(key, value);
	}
	const s = q.toString();
	return s ? `?${s}` : '';
}

/** Raised when the backend answers with a non-2xx status or is unreachable. */
export class ApiError extends Error {
	status: number;
	detail: unknown;

	constructor(status: number, detail: unknown, message?: string) {
		super(message ?? `Request failed with status ${status}`);
		this.name = 'ApiError';
		this.status = status;
		this.detail = detail;
	}
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	let response: Response;
	try {
		// Every JSON endpoint lives under `/api` so the API can never collide with a
		// client-side SPA route (e.g. the `/proofs` page vs the proofs resource).
		response = await fetch(`${API_BASE_URL}/api${path}`, {
			// `credentials: 'include'` sends the httponly auth cookie on same- and
			// cross-origin API calls (the backend sets allow_credentials to match).
			credentials: 'include',
			...init,
			headers: { 'Content-Type': 'application/json', ...init?.headers }
		});
	} catch (cause) {
		throw new ApiError(
			0,
			cause,
			`Could not reach the backend at ${API_BASE_URL || window.location.origin}. Is it running?`
		);
	}

	const text = await response.text();

	// The body should be JSON, but a proxy error page or the SPA index.html
	// fallback can return HTML. Parse defensively so a non-JSON body surfaces as
	// an ApiError rather than an unwrapped SyntaxError.
	let body: unknown = null;
	if (text) {
		try {
			body = JSON.parse(text);
		} catch {
			throw new ApiError(
				response.status,
				text,
				response.ok
					? 'The backend returned an unexpected non-JSON response.'
					: `Request failed with status ${response.status}.`
			);
		}
	}

	if (!response.ok) {
		const detail = extractDetail(body);
		throw new ApiError(response.status, detail, formatDetail(detail));
	}

	return body as T;
}

function extractDetail(body: unknown): unknown {
	if (body && typeof body === 'object' && 'detail' in body) {
		return (body as { detail: unknown }).detail;
	}
	return body;
}

/**
 * Render a FastAPI `detail` into a readable message. `detail` may be a plain
 * string, a list of strings (our compile-error path), or a list of Pydantic
 * validation-error objects (`{ msg, loc, ... }`).
 */
function formatDetail(detail: unknown): string | undefined {
	if (typeof detail === 'string') return detail;
	if (Array.isArray(detail)) {
		return detail
			.map((item) => {
				if (typeof item === 'string') return item;
				if (item && typeof item === 'object' && 'msg' in item) {
					return String((item as { msg: unknown }).msg);
				}
				return JSON.stringify(item);
			})
			.join('\n');
	}
	// fastapi-users password-policy failures come back as { code, reason }.
	if (detail && typeof detail === 'object' && 'reason' in detail) {
		return String((detail as { reason: unknown }).reason);
	}
	return undefined;
}

/**
 * The four child-CRUD endpoints every system part shares. `segment` is the URL
 * path segment (e.g. `line-types`), which is not always the same as the detail
 * JSON key (`lines`). `Read`/`Create`/`Update` are the part's schemas.
 */
function partCrud<Read, Create, Update>(segment: string) {
	const base = (systemId: string) => `/formal-systems/${systemId}/${segment}`;
	return {
		create: (systemId: string, payload: Create) =>
			request<Read>(base(systemId), { method: 'POST', body: JSON.stringify(payload) }),
		update: (systemId: string, childId: string, payload: Update) =>
			request<Read>(`${base(systemId)}/${childId}`, {
				method: 'PATCH',
				body: JSON.stringify(payload)
			}),
		remove: (systemId: string, childId: string) =>
			request<null>(`${base(systemId)}/${childId}`, { method: 'DELETE' }),
		/** Persist a new order; `ids` must be an exact permutation of the collection. */
		reorder: (systemId: string, ids: string[]) =>
			request<Read[]>(`${base(systemId)}/order`, { method: 'PUT', body: JSON.stringify({ ids }) })
	};
}

export const api = {
	health: () => request<HealthResponse>('/health'),

	// --- Authentication ------------------------------------------------------

	register: (email: string, password: string, displayName?: string) =>
		request<User>('/auth/register', {
			method: 'POST',
			body: JSON.stringify({
				email,
				password,
				display_name: displayName?.trim() ? displayName.trim() : null
			})
		}),

	/**
	 * Log in and receive the session cookie. fastapi-users' login endpoint reads
	 * OAuth2 form fields (`username`/`password`), not JSON, so this posts
	 * url-encoded data and returns nothing (a 204 that sets the cookie).
	 */
	login: (email: string, password: string) =>
		request<null>('/auth/login', {
			method: 'POST',
			headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
			body: new URLSearchParams({ username: email, password }).toString()
		}),

	logout: () => request<null>('/auth/logout', { method: 'POST' }),

	/** The configured social-login providers (e.g. ['google', 'github']). */
	oauthProviders: () => request<{ providers: string[] }>('/auth/providers'),

	/** The provider's authorization URL to send the browser to. */
	oauthAuthorizeUrl: (provider: string) =>
		request<{ authorization_url: string }>(`/auth/${provider}/authorize`),

	me: () => request<User>('/users/me'),

	updateProfile: (changes: { display_name?: string | null; password?: string }) =>
		request<User>('/users/me', {
			method: 'PATCH',
			body: JSON.stringify(changes)
		}),

	// --- Formal systems (stored CRUD) ---------------------------------------

	systems: {
		/** What a citation's label names, from rows — no re-check, so any reader of
		 * the system may ask. `proofs.justification` is the same thing plus the
		 * substitution, and costs a re-check for it. */
		libraryEntry: (
			systemId: string,
			label: string,
			options: { notation?: string; proof?: string } = {}
		) => {
			const query = new URLSearchParams();
			if (options.notation) query.set('notation', options.notation);
			// Only a label local to the citing proof needs it — a hypothesis of the
			// theorem that proof establishes, which no system-wide index can see.
			if (options.proof) query.set('proof', options.proof);
			const suffix = query.size ? `?${query}` : '';
			return request<LibraryEntry>(
				`/formal-systems/${systemId}/library/${encodeURIComponent(label)}${suffix}`
			);
		},
		/** The signed-in user's own systems (drafts included). Requires auth. */
		list: (params?: ListParams) =>
			request<Page<FormalSystemSummary>>(`/formal-systems${listQuery(params)}`),
		/** The shared master list: every published system, any owner, no auth. */
		listPublic: (params?: ListParams) =>
			request<Page<FormalSystemSummary>>(`/formal-systems/public${listQuery(params)}`),
		/** A single system. Published ones are public; drafts are owner-only. */
		get: (id: string) => request<FormalSystemDetail>(`/formal-systems/${id}`),
		/** A stored term's shape, node by node — what `ProofStructure` cannot say,
		 * since it gives each line's term as a root identity only.
		 *
		 * Flat, because a term is an interned DAG: a subterm two positions share is
		 * one node with one id, and every reference to it is that id. `notation`
		 * reads each node through one of the system's stored notations; `depth`
		 * bounds how far below the root to descend (nodes stopping short are
		 * marked `truncated`). */
		term: (systemId: string, termId: string, options?: { notation?: string; depth?: number }) => {
			const query = new URLSearchParams();
			if (options?.notation) query.set('notation', options.notation);
			if (options?.depth !== undefined) query.set('depth', String(options.depth));
			const suffix = query.size ? `?${query}` : '';
			return request<TermGraph>(`/formal-systems/${systemId}/terms/${termId}${suffix}`);
		},
		/** Which of this system's theorems could conclude a goal.
		 *
		 * A filter, and only a filter: candidates are narrowed by the root
		 * production of their conclusion — a column, indexed per system — and
		 * ranked by whether the α-digest says the conclusion already *is* the
		 * goal. Every one still has to unify, and this does not build the system
		 * to find out; `proofs.citations` does, because checking a proof has
		 * already built it. `term` is a stored term of this system: a proof
		 * line's statement, or any node `systems.term` returned. */
		matchingTheorems: (systemId: string, termId: string, limit?: number) => {
			const query = new URLSearchParams({ term: termId });
			if (limit !== undefined) query.set('limit', String(limit));
			return request<TheoremMatches>(
				`/formal-systems/${systemId}/theorems/matching?${query.toString()}`
			);
		},
		create: (payload: FormalSystemCreate) =>
			request<FormalSystemDetail>('/formal-systems', {
				method: 'POST',
				body: JSON.stringify(payload)
			}),
		update: (id: string, payload: FormalSystemUpdate) =>
			request<FormalSystemDetail>(`/formal-systems/${id}`, {
				method: 'PATCH',
				body: JSON.stringify(payload)
			}),
		remove: (id: string) => request<null>(`/formal-systems/${id}`, { method: 'DELETE' }),
		/** Assemble the stored rows and compile them, reporting any errors. */
		validate: (id: string) =>
			request<SystemValidation>(`/formal-systems/${id}/validate`, { method: 'POST' }),
		/** Verify a proof against this stored system, assembled server-side from
		 * rows — only the proof text is sent, never any system source. */
		verify: (id: string, proofText: string) =>
			request<VerifyResponse>(`/formal-systems/${id}/verify`, {
				method: 'POST',
				body: JSON.stringify({ proof_text: proofText })
			}),
		/** This system's folder tree, roots first — for an imported corpus, the
		 * outline its `.mm` file draws with section headers. Whole, not a level at a
		 * time: set.mm's is 1,903 nodes, one small response. */
		folders: (id: string) => request<Folder[]>(`/formal-systems/${id}/folders`),
		/** What this system records about one of the labels it names — a production,
		 * a definition, a primitive theorem or a proof alike, since that is how it is
		 * stored. 404s for a label it describes nothing about. */
		label: (id: string, label: string) =>
			request<LabelDescription>(
				`/formal-systems/${id}/labels/${encodeURIComponent(label)}`
			),
		/** Find a label from the words someone used for it — the corpus's own prose
		 * and proofs' own titles alike, across the whole inheritance spine.
		 *
		 * A substring match over words, ranked by where they landed, so it has no
		 * stemming and no synonyms: a query sharing no *word* with the prose scores
		 * nothing however well it describes it. `documented` says how much prose it
		 * looked through, so an empty answer is readable as one. */
		searchLabels: (
			id: string,
			q: string,
			params?: { limit?: number; offset?: number }
		) =>
			request<LabelSearch>(
				`/formal-systems/${id}/labels${listQuery(
					{ limit: params?.limit, offset: params?.offset },
					{ q }
				)}`
			)
	},

	// --- Relations between systems ------------------------------------------

	/**
	 * Edges *into* one system — the theorems its proofs may cite from elsewhere.
	 * The path names the **target**, since that is whose citations widen and
	 * whose owner may say so; the source need only be visible.
	 */
	relations: {
		list: (systemId: string) =>
			request<SystemRelation[]>(`/formal-systems/${systemId}/relations`),
		create: (systemId: string, payload: SystemRelationCreate) =>
			request<SystemRelation>(`/formal-systems/${systemId}/relations`, {
				method: 'POST',
				body: JSON.stringify(payload)
			}),
		update: (systemId: string, relationId: string, payload: SystemRelationUpdate) =>
			request<SystemRelation>(`/formal-systems/${systemId}/relations/${relationId}`, {
				method: 'PATCH',
				body: JSON.stringify(payload)
			}),
		remove: (systemId: string, relationId: string) =>
			request<null>(`/formal-systems/${systemId}/relations/${relationId}`, { method: 'DELETE' })
	},

	// --- Proofs (stored CRUD) -----------------------------------------------

	proofs: {
		/** The signed-in user's own proofs; optionally scoped to one system. */
		list: (formalSystemId?: string, params?: ListParams) =>
			request<Page<ProofSummary>>(
				`/proofs${listQuery(params, { formal_system_id: formalSystemId })}`
			),
		/** The shared master list: every published proof, any owner, no auth.
		 *
		 * Scope it to a system, or to one folder of that system's outline, to
		 * browse an imported corpus: unscoped it is 47,000 theorems in publication
		 * order, and an import publishes them all at once. A scoped page comes back
		 * in the proofs' own order within the system instead. */
		listPublic: (
			params?: ListParams,
			scope: { formalSystemId?: string; folderId?: string } = {}
		) =>
			request<Page<ProofSummary>>(
				`/proofs/public${listQuery(params, {
					formal_system_id: scope.formalSystemId,
					folder_id: scope.folderId
				})}`
			),
		/** A single proof. Published ones are public; drafts are owner-only. */
		get: (id: string) => request<ProofDetail>(`/proofs/${id}`),
		create: (payload: ProofCreate) =>
			request<ProofDetail>('/proofs', { method: 'POST', body: JSON.stringify(payload) }),
		update: (id: string, payload: ProofUpdate) =>
			request<ProofDetail>(`/proofs/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
		remove: (id: string) => request<null>(`/proofs/${id}`, { method: 'DELETE' }),
		/** Rebuild the parent system and check this proof against it, caching the verdict. */
		verify: (id: string) => request<VerifyResponse>(`/proofs/${id}/verify`, { method: 'POST' }),
		/** The structure the last verification stored — lines, their kernel terms,
		 * and the justification edges between them. Never re-checks: an unverified
		 * proof reports `stored: false`.
		 *
		 * `notation` names one of the parent system's stored notations
		 * (`FormalSystemDetail.notations`) to read the lines through; omitted, the
		 * lines carry only the source they were written in. */
		structure: (id: string, notation?: string) =>
			request<ProofStructure>(
				`/proofs/${id}/structure${notation ? `?notation=${encodeURIComponent(notation)}` : ''}`
			),
		/** Why a line follows: the rule its citation resolved to, that rule's own
		 * schemas, which cited line filled which premise, and the substitution the
		 * match derived. Re-checks the proof — the substitution is derived, not
		 * stored — so this is a request to make on demand, not per line.
		 *
		 * 404 for a line no citation justifies (a hole, a scope opener, a comment),
		 * which is not an error: which kind of unjustified it is belongs to the
		 * line's own `failure`. */
		justification: (id: string, number: number, notation?: string) =>
			request<LineJustification>(
				`/proofs/${id}/lines/${number}/justification` +
					(notation ? `?notation=${encodeURIComponent(notation)}` : '')
			),
		/** Justify a line by naming a rule and the lines it uses — no citation
		 * syntax crosses the wire. A dry run unless `apply` is set; applying is
		 * owner-only, as an edit is. Lines are addressed by citation number, which
		 * needs the proof's stored structure, so verify it first. */
		cite: (id: string, proposal: CitationProposal) =>
			request<CitationOutcome>(`/proofs/${id}/cite`, {
				method: 'POST',
				body: JSON.stringify(proposal)
			}),
		/** What could justify a line — proposals that have already been checked.
		 *
		 * The move between `verify` (this line is a hole) and `cite` (does *this*
		 * justification work): which justification to name. Every suggestion comes
		 * back in `CitationProposal`'s own shape, so acting on one is a copy into
		 * `cite` rather than a translation, and it applies — the search confirms
		 * with the check a verify runs, against the lines that stand above the
		 * goal. `candidates` bounds how many library entries the prefilter may
		 * offer for unification; zero searches the system's own rules only.
		 *
		 * Depth one: it finds the rule that justifies a line from lines that
		 * already stand. It does not prove a gap. */
		citations: (id: string, line: number, options?: { limit?: number; candidates?: number }) => {
			const query = new URLSearchParams();
			if (options?.limit !== undefined) query.set('limit', String(options.limit));
			if (options?.candidates !== undefined)
				query.set('candidates', String(options.candidates));
			const suffix = query.toString() ? `?${query.toString()}` : '';
			return request<CitationSearch>(`/proofs/${id}/lines/${line}/citations${suffix}`);
		},
		/** Add a line stating a proposed term — structure in, no surface syntax.
		 * The resolved term is rendered into the system's own spelling and parsed
		 * back; the line is refused unless what comes out is what went in. A dry
		 * run unless `apply` is set; applying is owner-only. */
		addLine: (id: string, proposal: LineProposal) =>
			request<LineOutcome>(`/proofs/${id}/lines`, {
				method: 'POST',
				body: JSON.stringify(proposal)
			}),
		/** Take a line back out, renumbering what follows up to close the gap.
		 * Refused when another line cites it — the dependents would lose their
		 * justification, and the response names them. A dry run unless `apply` is
		 * set; applying is owner-only. */
		removeLine: (id: string, removal: LineRemoval) =>
			request<LineRemovalOutcome>(`/proofs/${id}/lines/remove`, {
				method: 'POST',
				body: JSON.stringify(removal)
			}),
		/** Replace this proof's outgoing references (lemmas it cites) wholesale. */
		setReferences: (id: string, references: ProofReferenceInput[]) =>
			request<ProofDetail>(`/proofs/${id}/references`, {
				method: 'PUT',
				body: JSON.stringify({ references })
			}),
		/** Enter this proof's conclusion in its system's library, so proofs here —
		 * and in every system inheriting this one — can cite it by `label`. The
		 * proof must be published; omit `label` to use its slug.
		 *
		 * A `label` naming an **assumption** of the same system discharges it:
		 * the debt is replaced by this warrant, and whatever rested on it inherits
		 * what this proof rests on. Refused with a 409 unless the statements
		 * match, since paying a debt off and replacing an entry with a different
		 * claim are opposite things that look identical from the outside. */
		promote: (id: string, label?: string, metavariables?: Record<string, string>) =>
			request<PromotedTheorem>(`/proofs/${id}/promote`, {
				method: 'POST',
				body: JSON.stringify({ label: label ?? null, metavariables: metavariables ?? {} })
			}),
		/** Withdraw that entry. A no-op if the proof established none. */
		retire: (id: string) => request<null>(`/proofs/${id}/promote`, { method: 'DELETE' }),
		/** What this proof rests on that nobody has proved — itself, and every
		 * lemma proof and library entry it reaches. 409s if the proof has never
		 * been verified, since nothing has resolved its citations. */
		provenance: (id: string) => request<ProofProvenance>(`/proofs/${id}/provenance`),
		/** Which theorems this proof cites and which proofs cite it, computed from
		 * the stored lines rather than from `proof_references` — an import writes
		 * none of those, since a Metamath step cites a theorem rather than a
		 * lemma's line. Its own request because the detail read does not carry it.
		 *
		 * Named for the graph rather than `citations`, which on this client is
		 * already the *search* for a citation that would justify one line. */
		citationGraph: (id: string) => request<ProofCitations>(`/proofs/${id}/citations`)
	},

	/**
	 * Citable statements nobody has proved, and the register of what rests on
	 * them. Creating and withdrawing are the system owner's; reading a published
	 * system's is anyone's.
	 */
	statements: {
		/** Compose a statement from the grammar and ask what could conclude it —
		 * the first call a translation makes, and the one path from a constructor
		 * vocabulary to a stored term. Readable for any published system; storing
		 * requires owning it. */
		propose: (systemId: string, proposal: StatementProposal) =>
			request<StatementOutcome>(`/formal-systems/${systemId}/statements`, {
				method: 'POST',
				body: JSON.stringify(proposal)
			})
	},

	/**
	 * What a formal statement claims to be a formalization *of*. Nothing here is
	 * checked — the kernel has no opinion on whether a term is Theorem 3.2 of some
	 * paper — so the surface records the claim, attributes it, and makes its
	 * absence visible instead.
	 */
	formalizations: {
		/** Register an external work, or return the one already registered.
		 * Idempotent on (kind, identifier, version) — and a version is part of the
		 * identity, so a paper's v2 is a different document and a claim made
		 * against v1 keeps pointing at the v1 its author read. */
		registerSource: (document: SourceDocumentCreate) =>
			request<SourceDocument>('/sources', {
				method: 'POST',
				body: JSON.stringify(document)
			}),
		sources: (
			filters?: { kind?: string; identifier?: string },
			params?: ListParams
		) => request<Page<SourceDocument>>(`/sources${listQuery(params, { ...filters })}`),
		/** Claim that a term is a formalization of a result in a document. */
		claim: (claim: FormalizationCreate) =>
			request<Formalization>('/formalizations', {
				method: 'POST',
				body: JSON.stringify(claim)
			}),
		/** Claims, filtered. `unreviewed` is the one that matters: an unreviewed
		 * claim is the ordinary state, and listing them is what makes its absence
		 * visible rather than merely stated. */
		list: (
			filters?: {
				document_id?: string;
				formal_system_id?: string;
				proof_id?: string;
				unreviewed?: boolean;
			},
			params?: ListParams
		) =>
			request<Page<Formalization>>(
				`/formalizations${listQuery(params, {
					document_id: filters?.document_id,
					formal_system_id: filters?.formal_system_id,
					proof_id: filters?.proof_id,
					// Only when asked: `unreviewed=false` is the default and sending it
					// is noise, but sending nothing where `true` was meant would return
					// every claim including the reviewed ones — which is what the
					// `as ListParams` cast used to do silently for all four (found in
					// review).
					unreviewed: filters?.unreviewed ? 'true' : undefined
				})}`
			),
		get: (id: string) => request<Formalization>(`/formalizations/${id}`),
		/** Pass a verdict on somebody *else's* claim — the attestor is refused,
		 * since the whole value of "reviewed" is independence. */
		review: (id: string, review: FormalizationReview) =>
			request<Formalization>(`/formalizations/${id}/review`, {
				method: 'POST',
				body: JSON.stringify(review)
			}),
		/** Replace the glossary wholesale. Clears any review: a reviewer agreed
		 * with a reading of the paper's words, and these are those words. */
		setGlossary: (id: string, entries: GlossaryEntryInput[]) =>
			request<Formalization>(`/formalizations/${id}/glossary`, {
				method: 'PUT',
				body: JSON.stringify(entries)
			}),
		withdraw: (id: string) => request<null>(`/formalizations/${id}`, { method: 'DELETE' })
	},

	assumptions: {
		/** What this system asserts without proof, most depended-on first. */
		list: (systemId: string) =>
			request<Assumption[]>(`/formal-systems/${systemId}/assumptions`),
		/** One of them, with the entries resting on it named. */
		get: (systemId: string, label: string) =>
			request<AssumptionDetail>(
				`/formal-systems/${systemId}/assumptions/${encodeURIComponent(label)}`
			),
		/** Take one on. Owner only. */
		create: (systemId: string, assumption: AssumptionCreate) =>
			request<Assumption>(`/formal-systems/${systemId}/assumptions`, {
				method: 'POST',
				body: JSON.stringify(assumption)
			}),
		/** Withdraw one, so the label stops resolving. Refused with a 409 while
		 * any library entry rests on it — withdrawing then would leave those
		 * entries citable and reporting no assumptions. */
		withdraw: (systemId: string, label: string) =>
			request<null>(
				`/formal-systems/${systemId}/assumptions/${encodeURIComponent(label)}`,
				{ method: 'DELETE' }
			),
		/** Every assumption in a published system, most depended-on first — the
		 * register of what this database cannot yet justify. Public. */
		public: (params?: ListParams) =>
			request<Page<Assumption>>(`/assumptions/public${listQuery(params)}`)
	},

	/**
	 * Per-part CRUD, grouped by collection. Each exposes create / update / remove
	 * / reorder against `/formal-systems/{id}/{segment}`.
	 */
	parts: {
		sorts: partCrud<Sort, SortCreate, SortUpdate>('sorts'),
		productions: partCrud<Production, ProductionCreate, ProductionUpdate>('productions'),
		brackets: partCrud<BracketPair, BracketCreate, BracketUpdate>('brackets'),
		lineTypes: partCrud<LineType, LineTypeCreate, LineTypeUpdate>('line-types'),
		definitions: partCrud<Definition, DefinitionCreate, DefinitionUpdate>('definitions'),
		axioms: partCrud<Axiom, AxiomCreate, AxiomUpdate>('axioms'),
		rules: partCrud<Rule, RuleCreate, RuleUpdate>('rules')
	}
};
