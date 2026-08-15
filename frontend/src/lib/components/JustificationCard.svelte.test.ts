import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import JustificationCard from './JustificationCard.svelte';
import { api } from '$lib/api';
import type { LineJustification } from '$lib/api';

vi.mock('$lib/api', () => ({
	api: { proofs: { justification: vi.fn() }, systems: { libraryEntry: vi.fn() } },
	ApiError: class ApiError extends Error {
		status: number;
		constructor(status: number, message: string) {
			super(message);
			this.status = status;
		}
	}
}));

const apiMock = api as unknown as {
	proofs: { justification: ReturnType<typeof vi.fn> };
	systems: { libraryEntry: ReturnType<typeof vi.fn> };
};
const user = userEvent.setup();

function told(over: Partial<LineJustification> = {}): LineJustification {
	return {
		line: 3,
		citation: 'MP, 1, 2',
		kind: 'rule',
		label: 'MP',
		name: 'modus ponens',
		conclusion: 'q',
		premises: [
			{ position: 0, schema_form: 'p', number: 1, statement: 'x ∈ y', extra: false },
			{ position: 1, schema_form: '(p → q)', number: 2, statement: '…', extra: false }
		],
		assignments: [
			{ variable: 'p', stands_for: 'x ∈ y' },
			{ variable: 'q', stands_for: 'y ∈ x' }
		],
		provisos: [],
		discharges: null,
		title: null,
		proof_id: null,
		notation: null,
		...over
	};
}

// Braced, not a concise body: `mockResolvedValue` returns the mock, and Vitest
// reads a function returned from a hook as a *teardown* callback — so an implicit
// return calls the mock after every test, which hangs on any that leaves a
// deliberately pending promise.
beforeEach(() => {
	apiMock.proofs.justification.mockResolvedValue(told());
	apiMock.systems.libraryEntry.mockResolvedValue({
		label: 'imbi12d',
		name: '',
		kind: 'theorem',
		conclusion: '|- ( ph -> ( ps <-> ch ) )',
		premises: ['|- ( ph -> ( ps <-> th ) )'],
		discharges: null,
		title: 'Deduction joining two equivalences.',
		proof_id: 'p9',
		notation: null
	});
});
afterEach(() => {
	vi.clearAllMocks();
});

describe('a citation that can be expanded', () => {
	it('asks for nothing until it is opened', async () => {
		// The record is derived by a re-check, so a proof of thirty steps would be
		// thirty of those for cards nobody may open.
		render(JustificationCard, {
			props: { proofId: 'p1', number: 3, explain: true, citation: 'MP, 1, 2' }
		});

		expect(screen.getByRole('button', { name: /MP, 1, 2/ })).toBeInTheDocument();
		expect(apiMock.proofs.justification).not.toHaveBeenCalled();
	});

	it('explains the step once opened', async () => {
		render(JustificationCard, {
			props: { proofId: 'p1', number: 3, explain: true, citation: 'MP, 1, 2' }
		});

		await user.hover(screen.getByRole('button', { name: /MP, 1, 2/ }));

		// The half that makes the step checkable: what the rule's metavariables
		// stood for here.
		await waitFor(() => expect(screen.getByText('y ∈ x')).toBeInTheDocument());
		expect(apiMock.proofs.justification).toHaveBeenCalledWith('p1', 3, undefined);
	});

	it('reads the record in the notation the proof is being read in', async () => {
		// A reader looking at a proof in one spelling must not be handed the
		// substitution in another.
		render(JustificationCard, {
			props: { proofId: 'p1', number: 3, explain: true, citation: 'MP, 1, 2', notation: 'unicode' }
		});

		await user.hover(screen.getByRole('button', { name: /MP, 1, 2/ }));

		await waitFor(() =>
			expect(apiMock.proofs.justification).toHaveBeenCalledWith('p1', 3, 'unicode')
		);
	});

	it('links to the proof of the theorem it cited', async () => {
		// A library citation names a label; the proof of that label is a row away
		// and is not something a reader can find for themselves.
		apiMock.proofs.justification.mockResolvedValue(told({ label: 'imbi12d', proof_id: 'p9' }));
		render(JustificationCard, {
			props: { proofId: 'p1', number: 3, explain: true, citation: 'imbi12d, 2, 3' }
		});

		await user.hover(screen.getByRole('button', { name: /imbi12d/ }));

		const link = await screen.findByRole('link', { name: /Open the proof of imbi12d/ });
		expect(link).toHaveAttribute('href', '/proofs/p9');
		expect(link).toHaveAttribute('target', '_blank');
	});

	it('stays plain text with nothing at all to look up', () => {
		render(JustificationCard, { props: { citation: 'MP, 1, 2' } });

		expect(screen.getByText(/MP, 1, 2/)).toBeInTheDocument();
		expect(screen.queryByRole('button')).toBeNull();
	});
});

describe('reaching the card without a mouse', () => {
	it('is focusable, which is what lets it open without a pointer', async () => {
		// The primitive renders an anchor and this one has no href, so it is
		// tabbable only because the trigger asks to be. It opens on focus
		// (`LinkPreview`'s own `onfocus`), which jsdom cannot exercise — that path
		// is gated on `:focus-visible`, which it does not implement — so what is
		// pinned here is the half that made the trigger unreachable.
		render(JustificationCard, {
			props: { proofId: 'p1', number: 3, explain: true, citation: 'MP, 1, 2' }
		});

		const trigger = screen.getByRole('button', { name: /MP, 1, 2/ });
		expect(trigger).toHaveAttribute('tabindex', '0');

		await user.tab();
		expect(trigger).toHaveFocus();
	});
});

describe('switching notation while the card is up', () => {
	it('drops the previous reading rather than showing it under the new heading', async () => {
		const { rerender } = render(JustificationCard, {
			props: { proofId: 'p1', number: 3, explain: true, citation: 'MP, 1, 2' }
		});
		await user.hover(screen.getByRole('button', { name: /MP, 1, 2/ }));
		await waitFor(() => expect(screen.getByText('y ∈ x')).toBeInTheDocument());

		// Held open until asserted on, so the window between the switch and the
		// new reading landing is the thing under test.
		let land: (found: LineJustification) => void = () => {};
		apiMock.proofs.justification.mockImplementation(
			() => new Promise<LineJustification>((resolve) => (land = resolve))
		);
		await rerender({
			proofId: 'p1',
			number: 3,
			explain: true,
			citation: 'MP, 1, 2',
			notation: 'latex'
		});

		await waitFor(() => expect(screen.queryByText('y ∈ x')).toBeNull());
		expect(apiMock.proofs.justification).toHaveBeenLastCalledWith('p1', 3, 'latex');

		land(told({ assignments: [{ variable: 'q', stands_for: '\\varphi' }] }));
		await waitFor(() => expect(screen.getByText('\\varphi')).toBeInTheDocument());
	});
});

describe('a reader who is not signed in', () => {
	it('still learns what the citation names, from rows', async () => {
		// The substitution costs a re-check and a re-check needs an account; what
		// the label *says* does not, and it is most of what a reader wants on a
		// corpus of 47,546 theorems.
		render(JustificationCard, {
			props: { systemId: 's1', label: 'imbi12d', citation: 'imbi12d, 2, 3' }
		});

		await user.hover(screen.getByRole('button', { name: /imbi12d/ }));

		await waitFor(() =>
			expect(screen.getByText('Deduction joining two equivalences.')).toBeInTheDocument()
		);
		expect(screen.getByText('|- ( ph -> ( ps <-> ch ) )')).toBeInTheDocument();
		expect(await screen.findByRole('link', { name: /Open the proof of imbi12d/ })).toBeInTheDocument();
		// And it asks the cheap endpoint, never the one that re-checks.
		// No notation asked for, so none is passed on: the grammar's own spelling.
		// No notation asked for and no proof to resolve a local label against.
		expect(apiMock.systems.libraryEntry).toHaveBeenCalledWith('s1', 'imbi12d', {
			notation: undefined,
			proof: undefined
		});
		expect(apiMock.proofs.justification).not.toHaveBeenCalled();
	});

	it('shows no substitution, because none was derived for it', async () => {
		render(JustificationCard, {
			props: { systemId: 's1', label: 'imbi12d', citation: 'imbi12d, 2, 3' }
		});

		await user.hover(screen.getByRole('button', { name: /imbi12d/ }));
		await waitFor(() => expect(screen.getByText(/Deduction joining/)).toBeInTheDocument());

		expect(screen.queryByText('Here')).toBeNull();
	});

	it('asks the re-checking endpoint once there is a proof to ask about', async () => {
		render(JustificationCard, {
			props: {
				systemId: 's1',
				label: 'MP',
				proofId: 'p1',
				number: 3,
				explain: true,
				citation: 'MP, 1, 2'
			}
		});

		await user.hover(screen.getByRole('button', { name: /MP, 1, 2/ }));

		await waitFor(() => expect(screen.getByText('Here')).toBeInTheDocument());
		expect(apiMock.systems.libraryEntry).not.toHaveBeenCalled();
	});
});

describe('reading the card in the proof’s own notation', () => {
	it('asks the rows-only endpoint for the reading on screen', async () => {
		// The card sits beside a proof being read in one spelling; half a card in
		// each is worse than either.
		render(JustificationCard, {
			props: { systemId: 's1', label: 'imbi12d', citation: 'imbi12d, 2, 3', notation: 'unicode' }
		});

		await user.hover(screen.getByRole('button', { name: /imbi12d/ }));

		await waitFor(() =>
			expect(apiMock.systems.libraryEntry).toHaveBeenCalledWith('s1', 'imbi12d', {
				notation: 'unicode',
				proof: undefined
			})
		);
	});

	it('typesets the rule’s own schemas, not only the substitution', async () => {
		apiMock.systems.libraryEntry.mockResolvedValue({
			label: 'mp',
			name: '',
			kind: 'theorem',
			conclusion: '\\psi',
			premises: ['\\varphi', '\\varphi \\rightarrow \\psi'],
			discharges: null,
			title: null,
			proof_id: null,
			notation: 'latex'
		});
		render(JustificationCard, {
			props: { systemId: 's1', label: 'mp', citation: 'mp, 1, 2', notation: 'latex' }
		});

		await user.hover(screen.getByRole('button', { name: /mp, 1, 2/ }));

		// Three schemas — two premises and a conclusion — all set as mathematics.
		await waitFor(() =>
			expect(document.querySelectorAll('.katex-html').length).toBe(3)
		);
	});
});

describe('a label local to the proof doing the citing', () => {
	it('hands the proof over so a theorem’s own hypothesis resolves', async () => {
		// A `$e` is citable from inside the block that declares it and nowhere
		// else, so no system-wide lookup can see it — without the proof, the card
		// would 404 on a step of an imported theorem citing its own hypothesis.
		render(JustificationCard, {
			props: { systemId: 's1', label: 'mp2.1', proofId: 'p1', citation: 'mp2.1' }
		});

		await user.hover(screen.getByRole('button', { name: /mp2\.1/ }));

		await waitFor(() =>
			expect(apiMock.systems.libraryEntry).toHaveBeenCalledWith('s1', 'mp2.1', {
				notation: undefined,
				proof: 'p1'
			})
		);
		// And it stays on the cheap endpoint: a proof alone does not buy a re-check.
		expect(apiMock.proofs.justification).not.toHaveBeenCalled();
	});
});
