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
		/** The shared master list: every published proof, any owner, no auth. */
		listPublic: (params?: ListParams) =>
			request<Page<ProofSummary>>(`/proofs/public${listQuery(params)}`),
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
		/** Replace this proof's outgoing references (lemmas it cites) wholesale. */
		setReferences: (id: string, references: ProofReferenceInput[]) =>
			request<ProofDetail>(`/proofs/${id}/references`, {
				method: 'PUT',
				body: JSON.stringify({ references })
			}),
		/** Enter this proof's conclusion in its system's library, so proofs here —
		 * and in every system inheriting this one — can cite it by `label`. The
		 * proof must be published; omit `label` to use its slug. */
		promote: (id: string, label?: string, metavariables?: Record<string, string>) =>
			request<PromotedTheorem>(`/proofs/${id}/promote`, {
				method: 'POST',
				body: JSON.stringify({ label: label ?? null, metavariables: metavariables ?? {} })
			}),
		/** Withdraw that entry. A no-op if the proof established none. */
		retire: (id: string) => request<null>(`/proofs/${id}/promote`, { method: 'DELETE' })
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
