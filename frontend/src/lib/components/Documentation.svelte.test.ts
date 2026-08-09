import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import Documentation from './Documentation.svelte';
import type { LabelDescription } from '$lib/api';

function documentation(over: Partial<LabelDescription> = {}): LabelDescription {
	return {
		label: 'id',
		title: null,
		text: '',
		attributions: [],
		references: [],
		citations: [],
		mentioned_by: [],
		mentioned_by_total: 0,
		discouraged_usage: false,
		discouraged_modification: false,
		avoids: [],
		...over
	};
}

describe('a corpus record', () => {
	it('turns a reference to a readable proof into a link', () => {
		render(Documentation, {
			documentation: documentation({
				text: 'Uses ~ ax-1 for the step.',
				references: [
					{ target: 'ax-1', start: 5, end: 11, proof_id: 'p1', title: 'Axiom Simp.' }
				]
			})
		});

		const link = screen.getByRole('link', { name: 'ax-1' });
		expect(link).toHaveAttribute('href', '/proofs/p1');
		// The target's own first sentence, so hovering says what it is.
		expect(link).toHaveAttribute('title', 'Axiom Simp.');
		expect(screen.getByText(/Uses/)).toBeInTheDocument();
	});

	it('shows a reference it cannot follow as the label, not as markup', () => {
		// A definition or an axiom is documented but has no page of its own, and a
		// draft's id is withheld. `~ df-un` is still worse than `df-un`.
		render(Documentation, {
			documentation: documentation({
				text: 'See ~ df-un .',
				references: [{ target: 'df-un', start: 4, end: 11, proof_id: null, title: null }]
			})
		});

		expect(screen.queryByRole('link', { name: 'df-un' })).toBeNull();
		expect(screen.getByText('df-un')).toBeInTheDocument();
	});

	it('opens an external reference in a new tab', () => {
		render(Documentation, {
			documentation: documentation({
				text: 'See ~ https://example.com/p.pdf .',
				references: [
					{
						target: 'https://example.com/p.pdf',
						start: 4,
						end: 31,
						proof_id: null,
						title: null
					}
				]
			})
		});

		const link = screen.getByRole('link', { name: 'https://example.com/p.pdf' });
		expect(link).toHaveAttribute('target', '_blank');
		expect(link).toHaveAttribute('rel', 'noreferrer');
	});

	it('shows what points back, and says how many it is not showing', () => {
		// The direction the file cannot answer. `set.mm` points at `ax-13` from 656
		// statements, so the list is capped and the count carries the rest.
		render(Documentation, {
			documentation: documentation({
				mentioned_by: [
					{ label: 'a1i', proof_id: 'p2', title: null },
					{ label: 'mp2', proof_id: null, title: null }
				],
				mentioned_by_total: 42
			})
		});

		expect(screen.getByRole('link', { name: 'a1i' })).toHaveAttribute('href', '/proofs/p2');
		expect(screen.getByText('mp2')).toBeInTheDocument();
		expect(screen.getByText('and 40 more')).toBeInTheDocument();
	});

	it('says nothing about back-references when there are none', () => {
		render(Documentation, { documentation: documentation({ text: 'Prose.' }) });

		expect(screen.queryByText(/Mentioned by/)).toBeNull();
	});

	it('warns about each discouragement separately', () => {
		render(Documentation, {
			documentation: documentation({ discouraged_usage: true, discouraged_modification: true })
		});

		expect(screen.getByText('New usage is discouraged.')).toBeInTheDocument();
		expect(screen.getByText('Proof modification is discouraged.')).toBeInTheDocument();
	});

	it('warns about neither when the corpus says neither', () => {
		render(Documentation, { documentation: documentation({ text: 'Prose.' }) });

		expect(screen.queryByText(/discouraged/)).toBeNull();
	});
});

describe('what a proof is declared to do without', () => {
	it('lists the statements the corpus says it avoids', () => {
		// A result about the proof rather than the theorem, and nowhere else to read
		// it from: an avoided statement is usually nowhere in the citation graph.
		render(Documentation, {
			documentation: documentation({ avoids: ['ax-11', 'ax-12'] })
		});

		expect(screen.getByText('Proved without')).toBeInTheDocument();
		expect(screen.getByText('ax-11')).toBeInTheDocument();
		expect(screen.getByText('ax-12')).toBeInTheDocument();
	});

	it('says nothing when the corpus declares nothing', () => {
		render(Documentation, { documentation: documentation({ text: 'Prose.' }) });

		expect(screen.queryByText('Proved without')).toBeNull();
	});
});

describe('where the prose points outside the corpus', () => {
	it('shows a citation as the key and page it was written as', () => {
		render(Documentation, {
			documentation: documentation({
				text: 'Axiom A1 of [Margaris] p. 49.',
				citations: [{ work: 'Margaris', page: '49', start: 12, end: 28 }]
			})
		});

		expect(screen.getByText('[Margaris] p. 49')).toBeInTheDocument();
		expect(screen.getByText(/Axiom A1 of/)).toBeInTheDocument();
	});

	it('links a citation to the rest of the library from the same work', () => {
		// There is no work to open — the bibliography lives outside the `.mm` file —
		// so what the link offers is the other statements that came from it.
		render(Documentation, {
			documentation: documentation({
				text: 'Axiom A1 of [Margaris] p. 49.',
				citations: [{ work: 'Margaris', page: '49', start: 12, end: 28 }]
			}),
			systemId: 's1'
		});

		expect(screen.getByRole('link', { name: '[Margaris] p. 49' })).toHaveAttribute(
			'href',
			'/systems/s1/works/Margaris'
		);
	});

	it('shows a citation unlinked when there is no system to browse from', () => {
		render(Documentation, {
			documentation: documentation({
				text: 'Axiom A1 of [Margaris] p. 49.',
				citations: [{ work: 'Margaris', page: '49', start: 12, end: 28 }]
			})
		});

		expect(screen.queryByRole('link', { name: '[Margaris] p. 49' })).toBeNull();
	});

	it('shows the citation exactly as the file wrote it', () => {
		// 103 of set.mm's put a comma before the `p.`, which its own conventions
		// forbid. Rebuilding the label from the key and page drops it silently, so
		// the span is what renders (found in review).
		render(Documentation, {
			documentation: documentation({
				text: 'Lemma 6.1C.2 of [Shapiro], p. 199.',
				citations: [{ work: 'Shapiro', page: '199', start: 16, end: 33 }],
				references: []
			}),
			systemId: 's1'
		});

		expect(screen.getByRole('link', { name: '[Shapiro], p. 199' })).toBeInTheDocument();
	});

	it('says nothing extra when the prose cites nothing', () => {
		render(Documentation, { documentation: documentation({ text: 'Prose.' }) });

		expect(screen.getByText('Prose.')).toBeInTheDocument();
	});
});
