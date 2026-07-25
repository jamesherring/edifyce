import { API_BASE_URL } from './config';

// ---------------------------------------------------------------------------
// Response shapes — mirror app/schemas.py and the proof `.data()` payload.
// ---------------------------------------------------------------------------

export interface HealthResponse {
	status: string;
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
	bindings: Binding[];
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

export interface Definition {
	id: string;
	sort: string;
	name: string;
	higher: string;
	lower: string;
	/** Soundness provisos, one kernel-vocabulary line each (implicit conjunction),
	 * mirroring a rule's `side_conditions`. */
	provisos: string[];
	/** Deprecated: the provisos joined with `;` as one `where` string. Derived
	 * from the same tree as `provisos`; prefer `provisos`. */
	condition: string | null;
	bindings: Binding[];
	/** The defining form's bound variables (the `fresh` clause). Declaring them
	 * lets a quantified definition take the kernel path so its proviso is enforced. */
	fresh: Binding[];
	/** Optional name a proof cites this definition by (`[<label>, <line>]`); null
	 * when unnamed. Unique within a system. */
	label: string | null;
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
	sorts: Sort[];
	productions: Production[];
	lines: LineType[];
	definitions: Definition[];
	axioms: Axiom[];
	rules: Rule[];
}

export interface SystemValidation {
	success: boolean;
	errors: string[];
	system_name: string | null;
	line_type_count: number | null;
	inference_rule_count: number | null;
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
	bindings?: Binding[];
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
	/** Structured provisos (preferred), mirroring rules' `side_conditions`. */
	provisos?: string[];
	/** Deprecated: single `;`-joined `where` string. Ignored when `provisos` is
	 * supplied; kept so pre-D0 clients keep working. */
	condition?: string | null;
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
}

export interface ProofCreate {
	name: string;
	formal_system_id: string;
	description?: string | null;
	source?: string;
}

export interface ProofUpdate {
	name?: string;
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
			})
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
		/** Replace this proof's outgoing references (lemmas it cites) wholesale. */
		setReferences: (id: string, references: ProofReferenceInput[]) =>
			request<ProofDetail>(`/proofs/${id}/references`, {
				method: 'PUT',
				body: JSON.stringify({ references })
			})
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
