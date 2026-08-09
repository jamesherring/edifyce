import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import Provenance from './Provenance.svelte';
import type { ProofProvenance } from '$lib/api';

function provenance(over: Partial<ProofProvenance> = {}): ProofProvenance {
	return {
		proof_id: 'p1',
		assumes: [],
		unresolved: [],
		unread_lemmas: [],
		complete: true,
		...over
	};
}

const RIEMANN = {
	theorem_id: 't1',
	formal_system_id: 'sys1',
	label: 'riemann',
	statement: 'every nontrivial zero has real part 1/2',
	reason: 'Open. Assumed so the consequences can be developed.',
	source: 'Riemann 1859'
};

describe('what a proof rests on', () => {
	it('names each assumption and links to its page', () => {
		render(Provenance, { provenance: provenance({ assumes: [RIEMANN] }) });

		expect(screen.getByText(/conditional on 1 assumption\./)).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'riemann' })).toHaveAttribute(
			'href',
			'/systems/sys1/assumptions/riemann'
		);
		expect(screen.getByText(RIEMANN.statement)).toBeInTheDocument();
		expect(screen.getByText(/Assumed so the consequences/)).toBeInTheDocument();
		expect(screen.getByText('Riemann 1859')).toBeInTheDocument();
	});

	it('says nothing at all for a proof that rests on nothing', () => {
		const { container } = render(Provenance, { provenance: provenance() });

		// Not "assumes nothing" — an unconditional proof is the ordinary case, and
		// a badge for it would train readers to stop reading the panel.
		expect(container.textContent?.trim()).toBe('');
	});
});

describe('an incomplete report', () => {
	it('names the labels it could not account for', () => {
		render(Provenance, {
			provenance: provenance({ unresolved: ['mystery'], complete: false })
		});

		expect(screen.getByText('This report is incomplete.')).toBeInTheDocument();
		expect(screen.getByText('mystery')).toBeInTheDocument();
	});

	it('names the lemmas whose own debts could not be read', () => {
		render(Provenance, {
			provenance: provenance({ unread_lemmas: ['helper'], complete: false })
		});

		expect(screen.getByText('helper')).toBeInTheDocument();
		expect(screen.getByText(/Verifying them fills this in/)).toBeInTheDocument();
	});

	it('shows the caveat beside the assumptions rather than instead of them', () => {
		// The failure this exists to prevent: a short list read as a complete one.
		render(Provenance, {
			provenance: provenance({ assumes: [RIEMANN], unresolved: ['mystery'], complete: false })
		});

		expect(screen.getByRole('link', { name: 'riemann' })).toBeInTheDocument();
		expect(screen.getByText('This report is incomplete.')).toBeInTheDocument();
	});
});
