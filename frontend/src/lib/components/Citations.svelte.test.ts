import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import Citations from './Citations.svelte';
import type { ProofCitations } from '$lib/api';

function citations(over: Partial<ProofCitations> = {}): ProofCitations {
	return { cites: [], cited_by: [], cited_by_total: 0, ...over };
}

describe('what a proof cites', () => {
	it('links a cited theorem that has a proof of its own', () => {
		render(Citations, {
			citations: citations({
				cites: [{ label: 'a1i', proof_id: 'p1', title: 'Inference introducing an antecedent.' }]
			})
		});

		const link = screen.getByRole('link', { name: 'a1i' });
		expect(link).toHaveAttribute('href', '/proofs/p1');
		// The target's own first sentence, so hovering says what it is.
		expect(link).toHaveAttribute('title', 'Inference introducing an antecedent.');
	});

	it('shows a primitive as the label, with nothing to open', () => {
		// Half a corpus's labels are `$a`s that were never proved. The citation is
		// still real; there is simply no page.
		render(Citations, {
			citations: citations({ cites: [{ label: 'ax-mp', proof_id: null, title: null }] })
		});

		expect(screen.queryByRole('link', { name: 'ax-mp' })).toBeNull();
		expect(screen.getByText('ax-mp')).toBeInTheDocument();
	});

	it('says nothing when the proof cites nothing', () => {
		render(Citations, { citations: citations() });

		expect(screen.queryByText('Cites')).toBeNull();
	});
});

describe('what cites a proof', () => {
	it('shows the dependents and how many it is not showing', () => {
		// The direction a `.mm` file never states, and for a foundational statement
		// the answer is most of the library — so the list is capped.
		render(Citations, {
			citations: citations({
				cited_by: [
					{ label: '2a1i', proof_id: 'p2', title: null },
					{ label: 'mp2', proof_id: null, title: null }
				],
				cited_by_total: 431
			})
		});

		expect(screen.getByRole('link', { name: '2a1i' })).toHaveAttribute('href', '/proofs/p2');
		expect(screen.getByText('mp2')).toBeInTheDocument();
		expect(screen.getByText('and 429 more')).toBeInTheDocument();
	});

	it('shows no overflow note when the cap was not reached', () => {
		render(Citations, {
			citations: citations({
				cited_by: [{ label: '2a1i', proof_id: 'p2', title: null }],
				cited_by_total: 1
			})
		});

		expect(screen.queryByText(/more$/)).toBeNull();
	});

	it('says nothing when nothing cites it', () => {
		render(Citations, { citations: citations({ cites: [] }) });

		expect(screen.queryByText('Cited by')).toBeNull();
	});
});
