import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import JustificationCard from './JustificationCard.svelte';
import { api } from '$lib/api';
import type { LineJustification } from '$lib/api';

vi.mock('$lib/api', () => ({
	api: { proofs: { justification: vi.fn() } },
	ApiError: class ApiError extends Error {
		status: number;
		constructor(status: number, message: string) {
			super(message);
			this.status = status;
		}
	}
}));

const apiMock = api as unknown as { proofs: { justification: ReturnType<typeof vi.fn> } };
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

beforeEach(() => apiMock.proofs.justification.mockResolvedValue(told()));
afterEach(() => vi.clearAllMocks());

describe('a citation that can be expanded', () => {
	it('asks for nothing until it is opened', async () => {
		// The record is derived by a re-check, so a proof of thirty steps would be
		// thirty of those for cards nobody may open.
		render(JustificationCard, { props: { proofId: 'p1', number: 3, citation: 'MP, 1, 2' } });

		expect(screen.getByRole('button', { name: /MP, 1, 2/ })).toBeInTheDocument();
		expect(apiMock.proofs.justification).not.toHaveBeenCalled();
	});

	it('explains the step once opened', async () => {
		render(JustificationCard, { props: { proofId: 'p1', number: 3, citation: 'MP, 1, 2' } });

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
			props: { proofId: 'p1', number: 3, citation: 'MP, 1, 2', notation: 'unicode' }
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
		render(JustificationCard, { props: { proofId: 'p1', number: 3, citation: 'imbi12d, 2, 3' } });

		await user.hover(screen.getByRole('button', { name: /imbi12d/ }));

		const link = await screen.findByRole('link', { name: /Open the proof of imbi12d/ });
		expect(link).toHaveAttribute('href', '/proofs/p9');
		expect(link).toHaveAttribute('target', '_blank');
	});

	it('stays plain text with no proof to explain it against', () => {
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
		render(JustificationCard, { props: { proofId: 'p1', number: 3, citation: 'MP, 1, 2' } });

		const trigger = screen.getByRole('button', { name: /MP, 1, 2/ });
		expect(trigger).toHaveAttribute('tabindex', '0');

		await user.tab();
		expect(trigger).toHaveFocus();
	});
});
