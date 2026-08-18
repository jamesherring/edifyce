import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import Page from './+page.svelte';
import { auth } from '$lib/auth.svelte';
import { api, ApiError } from '$lib/api';
import type {
	LabelDescription,
	ProofDetail,
	ProofLine,
	ProofStructure,
	ProofStructureLine
} from '$lib/api';

vi.mock('$app/navigation', () => ({ goto: vi.fn(), beforeNavigate: vi.fn() }));
vi.mock('$app/state', () => ({ page: { params: { id: 'p1' } } }));
vi.mock('$lib/api', () => ({
	api: {
		me: vi.fn(),
		logout: vi.fn().mockResolvedValue(undefined),
		proofs: {
			get: vi.fn(),
			verify: vi.fn(),
			structure: vi.fn(),
			citationGraph: vi.fn(),
			provenance: vi.fn()
		},
		systems: { get: vi.fn() }
	},
	ApiError: class ApiError extends Error {
		status: number;
		constructor(status: number, detail: unknown, message?: string) {
			super(message ?? String(detail));
			this.status = status;
		}
	}
}));

const apiMock = api as unknown as {
	me: ReturnType<typeof vi.fn>;
	logout: ReturnType<typeof vi.fn>;
	proofs: {
		get: ReturnType<typeof vi.fn>;
		verify: ReturnType<typeof vi.fn>;
		structure: ReturnType<typeof vi.fn>;
		citationGraph: ReturnType<typeof vi.fn>;
		provenance: ReturnType<typeof vi.fn>;
	};
	systems: { get: ReturnType<typeof vi.fn> };
};

function structureLine(over: Partial<ProofStructureLine> = {}): ProofStructureLine {
	return {
		id: 'l1',
		position: 0,
		number: 1,
		indent: 0,
		display: '( sqrt ` 2 ) e. RR',
		line_type: 'Derivation',
		behaviour: null,
		label: null,
		reference: 'HYP',
		rule: null,
		definition_id: null,
		valid: true,
		invalid_message: null,
		failure: null,
		warning_message: null,
		opens_scope: null,
		scope_id: null,
		term: null,
		rendered: null,
		antecedents: [],
		...over
	};
}

function structure(lines: ProofStructureLine[], notation: string | null = null): ProofStructure {
	return { proof_id: 'p1', stored: true, notation, lines };
}

/** One line of `ProofDetail.result` — the display snapshot of the last check,
 *  which is what a proof verified before the structure store existed still has. */
function payloadLine(over: Partial<ProofLine> = {}): ProofLine {
	return {
		valid: true,
		number: 1,
		behaviour: null,
		name: 'Derivation',
		invalid_message: null,
		warning_message: null,
		reference: 'HYP',
		label: null,
		display: '( sqrt ` 2 ) e. RR',
		indent: 0,
		...over
	};
}

/** A system whose only interesting features are its notations, which reading it
 *  opens in, and where it came from — all of which the proof page reads off the
 *  system, not the proof. `lines` is carried because the page reads the primary
 *  line type off it, and a fixture without one throws where the real payload
 *  never would. */
function system(over: Record<string, unknown> = {}) {
	return {
		name: 'set.mm',
		notations: [],
		default_notation: null,
		lines: [],
		provenance: null,
		...over
	};
}

/** Choose a reading from the notation picker, by the label the option carries. */
async function pickReading(label: string) {
	await userEvent.click(await screen.findByRole('combobox', { name: 'Reading' }));
	await userEvent.click(await screen.findByText(label));
}

function detail(over: Partial<ProofDetail> = {}): ProofDetail {
	return {
		id: 'p1',
		name: 'sqrt2irr',
		slug: 'sqrt2irr',
		title: null,
		description: null,
		formal_system_id: 'sys1',
		folder_id: null,
		valid: true,
		published_at: '2020-01-01T00:00:00Z',
		created_at: '2020-01-01T00:00:00Z',
		updated_at: '2020-01-01T00:00:00Z',
		owner: null,
		source: 'x = x [HYP]',
		result: null,
		references: [],
		referenced_by: [],
		theorem: null,
		documentation: null,
		...over
	};
}

/** A corpus record, with the parts a test does not care about defaulted. */
function documentation(over: Partial<LabelDescription> = {}): LabelDescription {
	return {
		label: 'sqrt2irr',
		title: 'The square root of 2 is irrational.',
		text: '',
		attributions: [],
		references: [],
		citations: [],
		mentioned_by: [],
		mentioned_by_total: 0,
		discouraged_usage: false,
		discouraged_modification: false,
		claims: [],
		...over
	};
}

/** Sign a reader in. Verifying a proof needs an account — it rebuilds the whole
 *  system and re-checks against it — so a test that clicks Verify has to. */
async function signIn() {
	apiMock.me.mockResolvedValue({
		id: 'u1',
		email: 'a@b.c',
		is_active: true,
		is_superuser: false,
		is_verified: true,
		display_name: 'Ada'
	});
	await auth.refresh();
}

beforeEach(async () => {
	apiMock.logout.mockResolvedValue(undefined);
	apiMock.me.mockRejectedValue(new Error('anonymous'));
	apiMock.systems.get.mockRejectedValue(new Error('not readable'));
	// The two side panels: quiet by default, so a test that does not name them
	// renders neither.
	apiMock.proofs.citationGraph.mockRejectedValue(new Error('no graph'));
	// A 409 — the never-verified case, which renders nothing at all.
	apiMock.proofs.provenance.mockRejectedValue(new ApiError(409, 'verify it first'));
	apiMock.proofs.structure.mockResolvedValue({
		proof_id: 'p1',
		stored: false,
		notation: null,
		lines: []
	});
	await auth.refresh();
});
afterEach(async () => {
	await auth.logout();
	vi.clearAllMocks();
});

describe('the proof detail page', () => {
	it('leads with the title and keeps the label beside it', async () => {
		// On an imported corpus `name` is the opaque label a citation spells and
		// the title is the only readable thing there, so the sentence is the
		// heading — but the label is the identity the rest of the library refers
		// to, and has to stay visible.
		apiMock.proofs.get.mockResolvedValue(
			detail({ title: 'The square root of 2 is irrational.' })
		);
		render(Page);

		await waitFor(() =>
			expect(
				screen.getByRole('heading', { name: 'The square root of 2 is irrational.' })
			).toBeInTheDocument()
		);
		expect(screen.getByText('sqrt2irr')).toBeInTheDocument();
	});

	it('falls back to the label as the heading when there is no title', async () => {
		apiMock.proofs.get.mockResolvedValue(detail());
		render(Page);

		await waitFor(() =>
			expect(screen.getByRole('heading', { name: 'sqrt2irr' })).toBeInTheDocument()
		);
	});

	it('keeps the description visible when a title is also set', async () => {
		// Both are settable through `ProofCreate`/`ProofUpdate`, and the header
		// shows one line. Preferring the title there must not make an author's own
		// description disappear from the page — so it gets a place of its own.
		apiMock.proofs.get.mockResolvedValue(
			detail({ title: 'A short title.', description: 'A longer account of what this proves.' })
		);
		render(Page);

		await waitFor(() => expect(screen.getByText('A short title.')).toBeInTheDocument());
		expect(screen.getByText('A longer account of what this proves.')).toBeInTheDocument();
	});

	it('shows a description once when there is no title to show beside it', async () => {
		// The proof's own prose and the corpus's record sit in the same card, and a
		// hand-authored proof has only the first of them.
		apiMock.proofs.get.mockResolvedValue(detail({ description: 'Only a description.' }));
		render(Page);

		await waitFor(() => expect(screen.getByText('Only a description.')).toBeInTheDocument());
		expect(screen.getAllByText('Only a description.')).toHaveLength(1);
	});

	it('shows the corpus record with its authorship', async () => {
		apiMock.proofs.get.mockResolvedValue(
			detail({
				title: 'The square root of 2 is irrational.',
				documentation: documentation({
					text: 'Theorem 1.10 of [Apostol] p. 28.',
					attributions: [{ kind: 'Contributed', who: 'NM', dated: '20-Aug-2001' }]
				})
			})
		);
		render(Page);

		await waitFor(() =>
			expect(screen.getByText('Theorem 1.10 of [Apostol] p. 28.')).toBeInTheDocument()
		);
		expect(screen.getByText(/Contributed/)).toBeInTheDocument();
		expect(screen.getByText(/NM, 20-Aug-2001/)).toBeInTheDocument();
	});

	it('credits the library an imported proof came from', async () => {
		// Recorded once on the system, so this is the read that makes it reach the
		// 47,000 proofs filed against it.
		apiMock.proofs.get.mockResolvedValue(detail());
		apiMock.systems.get.mockResolvedValue(
			system({ provenance: "Imported from Metamath's set.mm library. See https://us.metamath.org/" })
		);
		render(Page);

		await waitFor(() =>
			expect(
				screen.getByText(/Imported from Metamath's set\.mm library/)
			).toBeInTheDocument()
		);
	});

	it('shows the checked lines rather than the source a browser cannot edit', async () => {
		apiMock.proofs.get.mockResolvedValue(detail());
		apiMock.proofs.structure.mockResolvedValue(structure([structureLine()]));
		render(Page);

		await waitFor(() => expect(screen.getByText('( sqrt ` 2 ) e. RR')).toBeInTheDocument());
		// One view, not a source pane beside a verification pane saying the same
		// thing: the source block is the fallback for a proof with no structure.
		expect(screen.queryByText('As written; verify it to see it line by line.')).toBeNull();
		expect(screen.getByText('by HYP')).toBeInTheDocument();
	});

	it('keeps the source visible for a proof that has never been checked', async () => {
		apiMock.proofs.get.mockResolvedValue(detail());
		render(Page);

		await waitFor(() => expect(screen.getByText('x = x [HYP]')).toBeInTheDocument());
	});

	it('re-reads the checked lines through a chosen notation', async () => {
		apiMock.proofs.get.mockResolvedValue(detail());
		apiMock.systems.get.mockResolvedValue(system({ notations: ['unicode'] }));
		apiMock.proofs.structure.mockImplementation(async (_id: string, name?: string) =>
			name === 'unicode'
				? structure([structureLine({ rendered: '(√‘2) ∈ ℝ' })], 'unicode')
				: structure([structureLine()])
		);
		render(Page);

		// No TeX notation and no stored default, so it opens in the source.
		await waitFor(() => expect(screen.getByText('( sqrt ` 2 ) e. RR')).toBeInTheDocument());
		await pickReading('unicode');

		// The same row, diagnostics and all — a notation re-spells the term, it
		// does not fetch a second rendering of the line.
		await waitFor(() => expect(screen.getByText('(√‘2) ∈ ℝ')).toBeInTheDocument());
		expect(screen.getByText('by HYP')).toBeInTheDocument();
	});

	it('opens a system with a TeX notation typeset, without being asked', async () => {
		// Typeset mathematics is the friendlier read, so a system carrying a TeX
		// notation opens in it rather than in the source spelling.
		apiMock.proofs.get.mockResolvedValue(detail());
		apiMock.systems.get.mockResolvedValue(system({ notations: ['latex'] }));
		apiMock.proofs.structure.mockImplementation(async (_id: string, name?: string) =>
			name === 'latex'
				? structure([structureLine({ rendered: '\\sqrt{2} \\in \\mathbb{R}' })], 'latex')
				: structure([structureLine()])
		);
		render(Page);

		// `.katex-html` is the rendering; the TeX stays in the DOM beside it, in
		// KaTeX's MathML annotation, which is what a screen reader reads.
		await waitFor(() => expect(document.querySelector('.katex-html')).not.toBeNull());
		// And the source was never rendered on the way there — one read, not two.
		expect(apiMock.proofs.structure).toHaveBeenCalledTimes(1);
	});

	it('opens in the reading the system stores, over the TeX one', async () => {
		apiMock.proofs.get.mockResolvedValue(detail());
		apiMock.systems.get.mockResolvedValue(
			system({ notations: ['unicode', 'latex'], default_notation: 'unicode' })
		);
		apiMock.proofs.structure.mockImplementation(async (_id: string, name?: string) =>
			name === 'unicode'
				? structure([structureLine({ rendered: '(√‘2) ∈ ℝ' })], 'unicode')
				: structure([structureLine()])
		);
		render(Page);

		await waitFor(() => expect(screen.getByText('(√‘2) ∈ ℝ')).toBeInTheDocument());
	});

	it('falls back to the source when the stored default names a notation that is gone', async () => {
		// The setting and the notations are edited apart, so a default can outlive
		// what it names; asking for it would only earn an error on every proof.
		apiMock.proofs.get.mockResolvedValue(detail());
		apiMock.systems.get.mockResolvedValue(
			system({ notations: [], default_notation: 'unicode' })
		);
		apiMock.proofs.structure.mockResolvedValue(structure([structureLine()]));
		render(Page);

		await waitFor(() => expect(screen.getByText('( sqrt ` 2 ) e. RR')).toBeInTheDocument());
		expect(apiMock.proofs.structure).toHaveBeenCalledWith('p1', undefined);
	});

	it('typesets by the reading on screen, not the one being fetched', async () => {
		// The rows deliberately stay up while the next reading loads, so keying the
		// typesetter off the *selection* would show a latex reading as raw source
		// for the round trip back to Source (and feed a unicode one to KaTeX on the
		// way out, which mostly parses rather than falling back).
		apiMock.proofs.get.mockResolvedValue(detail());
		apiMock.systems.get.mockResolvedValue(system({ notations: ['latex'] }));
		apiMock.proofs.structure.mockImplementation(async (_id: string, name?: string) =>
			name === 'latex'
				? structure([structureLine({ rendered: '\\sqrt{2} \\in \\mathbb{R}' })], 'latex')
				: structure([structureLine()])
		);
		render(Page);

		// Opens typeset, being a system with a TeX notation.
		await waitFor(() => expect(document.querySelector('.katex-html')).not.toBeNull());

		// Switch back, with the source reading never arriving.
		apiMock.proofs.structure.mockImplementation(() => new Promise(() => {}));
		await pickReading('Source');

		// The picker follows the *selection*, so what it shows marks the window the
		// rows are still the previous reading's — while the latex stays typeset.
		await waitFor(() =>
			expect(screen.getByRole('combobox', { name: 'Reading' })).toHaveTextContent('Source')
		);
		expect(document.querySelector('.katex-html')).not.toBeNull();
	});

	it('offers a signed-out reader the sign-in rather than the check', async () => {
		// Reading a published proof is open; re-checking one is not, since it rebuilds
		// the whole system and checks against it. Better a missing button than a 401
		// after the click.
		apiMock.proofs.get.mockResolvedValue(detail());
		render(Page);

		await waitFor(() =>
			expect(screen.getByRole('link', { name: /Sign in to verify/ })).toBeInTheDocument()
		);
		expect(screen.queryByRole('button', { name: 'Verify' })).toBeNull();
	});

	it('drops the previous check’s lines when a new verdict arrives', async () => {
		// The badge is `result`'s and the rows were the structure's, so leaving the
		// structure up across a verify puts a fresh "Valid" over stale red rows.
		apiMock.proofs.get.mockResolvedValue(detail());
		apiMock.proofs.structure.mockResolvedValueOnce(
			structure([structureLine({ valid: false, invalid_message: 'MP does not apply.' })])
		);
		apiMock.proofs.verify.mockResolvedValue({
			success: true,
			errors: [],
			proof: { indicator: 'ok', lines: [payloadLine({ display: 'x = x' })] }
		});
		await signIn();
		render(Page);

		await waitFor(() => expect(screen.getByText('MP does not apply.')).toBeInTheDocument());

		// The re-read never lands, so what is on screen is what the verify itself
		// returned — which is the point: fresh, not stale.
		apiMock.proofs.structure.mockImplementation(() => new Promise(() => {}));
		screen.getByRole('button', { name: 'Verify' }).click();

		await waitFor(() => expect(screen.getByText('x = x')).toBeInTheDocument());
		expect(screen.queryByText('MP does not apply.')).toBeNull();
	});

	it('does not ask what a never-checked proof rests on', async () => {
		// The route reads the citations a check *resolved*, so for an unchecked proof
		// the request can only 409 — and producing the report costs a chain load.
		apiMock.proofs.get.mockResolvedValue(detail({ valid: null }));
		render(Page);

		await waitFor(() => expect(screen.getByText('sqrt2irr')).toBeInTheDocument());
		expect(apiMock.proofs.provenance).not.toHaveBeenCalled();
	});

	it('lets the check’s provenance read win over the page load’s, however they land', async () => {
		// Both reads are for the same proof, so a page-level sequence cannot tell
		// them apart — and the pre-verify one resolving last would report the
		// previous check's debts as this one's, or none at all.
		const assumed = {
			theorem_id: 't1',
			formal_system_id: 'sys1',
			label: 'riemann',
			statement: 'RH',
			reason: 'Open.',
			source: null
		};
		let releaseFirst: (value: unknown) => void = () => {};
		apiMock.proofs.get.mockResolvedValue(detail());
		apiMock.proofs.verify.mockResolvedValue({
			success: true,
			errors: [],
			proof: { indicator: 'ok', lines: [payloadLine()] }
		});
		// The page load's read hangs; the check's read answers immediately.
		apiMock.proofs.provenance
			.mockImplementationOnce(
				() =>
					new Promise((resolve) => {
						releaseFirst = resolve;
					})
			)
			.mockResolvedValueOnce({
				proof_id: 'p1',
				assumes: [assumed],
				unresolved: [],
				unread_lemmas: [],
				complete: true
			});
		await signIn();
		render(Page);

		await waitFor(() => expect(screen.getByRole('button', { name: 'Verify' })).toBeEnabled());
		screen.getByRole('button', { name: 'Verify' }).click();

		expect(await screen.findByRole('link', { name: 'riemann' })).toBeInTheDocument();

		// Now the stale one lands, claiming the proof rests on nothing.
		releaseFirst({
			proof_id: 'p1',
			assumes: [],
			unresolved: [],
			unread_lemmas: [],
			complete: true
		});
		await waitFor(() =>
			expect(screen.getByRole('link', { name: 'riemann' })).toBeInTheDocument()
		);
	});

	it('shows a cached verdict’s lines instead of the source beside them', async () => {
		// A proof checked before the structure store existed has a payload and no
		// rows to project. Falling back to it in *both* places would render the
		// line list and the source block together — the pair this change removes.
		apiMock.proofs.get.mockResolvedValue(
			detail({ result: { indicator: 'ok', lines: [payloadLine()] } })
		);
		render(Page);

		await waitFor(() => expect(screen.getByText('( sqrt ` 2 ) e. RR')).toBeInTheDocument());
		expect(screen.queryByText('As written; verify it to see it line by line.')).toBeNull();
	});
});

it('falls back to the label when the title is cleared to an empty string', async () => {
	// `PATCH /proofs/{id}` accepts an empty title, and a nullish fallback treats it
	// as one — blank heading, and no label badge either, since the badge only
	// shows when a title is showing beside it. Found in review.
	apiMock.proofs.get.mockResolvedValue(detail({ title: '', name: 'sqrt2irr' }));
	render(Page);

	await waitFor(() => expect(screen.getByRole('heading', { name: 'sqrt2irr' })).toBeInTheDocument());
});
