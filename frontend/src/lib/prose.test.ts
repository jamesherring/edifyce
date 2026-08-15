import { describe, expect, it } from 'vitest';
import { renderProse, referenceHref } from './prose';
import type { LabelDescription, LabelReference } from '$lib/api';

function reference(over: Partial<LabelReference> = {}): LabelReference {
	return { target: 'ax-1', start: 0, end: 6, proof_id: null, title: null, ...over };
}

function description(over: Partial<LabelDescription> = {}): LabelDescription {
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
		claims: [],
		...over
	};
}

describe('splitting prose at its cross-references', () => {
	it('slices the text at the offsets the API sent', () => {
		// The whole contract: the markup rule lives in the engine and this slices.
		const doc = description({
			text: 'Uses ~ ax-1 for the step.',
			references: [reference({ start: 5, end: 11 })]
		});

		expect(renderProse(doc)).toEqual([
			{ kind: 'text', text: 'Uses ' },
			{ kind: 'reference', reference: doc.references[0] },
			{ kind: 'text', text: ' for the step.' }
		]);
	});

	it('keeps several references in order with the prose between them', () => {
		const doc = description({
			text: 'From ~ ax-1 and ~ ax-2 .',
			references: [
				reference({ target: 'ax-1', start: 5, end: 11 }),
				reference({ target: 'ax-2', start: 16, end: 22 })
			]
		});

		expect(renderProse(doc).map((s) => (s.kind === 'text' ? s.text : s.kind === 'citation' ? s.citation.work : s.reference.target))).toEqual(
			['From ', 'ax-1', ' and ', 'ax-2', ' .']
		);
	});

	it('handles a reference at the very start and the very end', () => {
		const doc = description({
			text: '~ ax-1',
			references: [reference({ start: 0, end: 6 })]
		});

		expect(renderProse(doc)).toEqual([{ kind: 'reference', reference: doc.references[0] }]);
	});

	it('returns the whole text when nothing points anywhere', () => {
		expect(renderProse(description({ text: 'Just prose.' }))).toEqual([
			{ kind: 'text', text: 'Just prose.' }
		]);
	});

	it('drops an offset that would reorder or duplicate the prose', () => {
		// Nothing should produce one — the offsets are written by the same pass that
		// assembled the text — but a stale row surviving a schema change must
		// degrade to plain prose rather than to scrambled prose.
		const doc = description({
			text: 'Uses ~ ax-1 here.',
			references: [
				reference({ start: 5, end: 11 }),
				reference({ target: 'ax-2', start: 2, end: 8 }), // overlaps backwards
				reference({ target: 'ax-3', start: 40, end: 60 }) // past the end
			]
		});

		expect(renderProse(doc).map((s) => (s.kind === 'text' ? s.text : s.kind === 'citation' ? s.citation.work : s.reference.target))).toEqual(
			['Uses ', 'ax-1', ' here.']
		);
	});
});

describe('where a reference points', () => {
	it('prefers the proof, which is the page that shows the statement', () => {
		expect(referenceHref(reference({ proof_id: 'p1', target: 'ax-1' }))).toBe('/proofs/p1');
	});

	it('follows an absolute URL as written', () => {
		// 242 of set.mm's references are papers and 32 are pages of the Metamath site.
		expect(referenceHref(reference({ target: 'https://example.com/paper.pdf' }))).toBe(
			'https://example.com/paper.pdf'
		);
	});

	it('has nowhere to send a label with no proof behind it', () => {
		// A definition or an axiom is documented but has no page of its own yet, and
		// a draft's id is deliberately withheld.
		expect(referenceHref(reference({ target: 'df-un' }))).toBeNull();
		expect(referenceHref(reference({ target: 'mmset.html#class' }))).toBeNull();
	});
});

describe('citations interleaved with references', () => {
	it('slices both kinds in the order they appear', () => {
		const doc = description({
			text: 'Theorem 1 of [Monk1] p. 22; see also ~ ax-1 .',
			citations: [{ work: 'Monk1', page: '22', start: 13, end: 26 }],
			references: [reference({ target: 'ax-1', start: 37, end: 43 })]
		});

		expect(
			renderProse(doc).map((s) =>
				s.kind === 'text' ? s.text : s.kind === 'citation' ? s.citation.work : s.reference.target
			)
		).toEqual(['Theorem 1 of ', 'Monk1', '; see also ', 'ax-1', ' .']);
	});

	it('handles a reference before a citation just as readily', () => {
		const doc = description({
			text: 'From ~ ax-1 , as in [Monk1] p. 9.',
			citations: [{ work: 'Monk1', page: '9', start: 20, end: 32 }],
			references: [reference({ target: 'ax-1', start: 5, end: 11 })]
		});

		expect(renderProse(doc).map((s) => s.kind)).toEqual([
			'text',
			'reference',
			'text',
			'citation',
			'text'
		]);
	});

	it('drops a citation that would overlap a reference', () => {
		// Nothing produces one — a `~` and a `[` are different characters — but a
		// stale row must degrade to plain prose rather than to scrambled prose.
		const doc = description({
			text: 'Uses ~ ax-1 here.',
			references: [reference({ start: 5, end: 11 })],
			citations: [{ work: 'Bad', page: '1', start: 7, end: 14 }]
		});

		expect(renderProse(doc).map((s) => s.kind)).toEqual(['text', 'reference', 'text']);
	});

	it('carries the span verbatim, not a reconstruction of it', () => {
		const doc = description({
			text: 'Lemma 6.1C.2 of [Shapiro], p. 199.',
			citations: [{ work: 'Shapiro', page: '199', start: 16, end: 33 }]
		});

		const [, citation] = renderProse(doc);
		expect(citation.kind === 'citation' && citation.text).toBe('[Shapiro], p. 199');
	});

	it('keeps prose whole when there are no citations', () => {
		expect(renderProse(description({ text: 'Just prose.' }))).toEqual([
			{ kind: 'text', text: 'Just prose.' }
		]);
	});
});

describe('a span the prose cannot hold', () => {
	it('drops it without taking the spans after it down too', () => {
		// The per-list ordering pass advances a cursor, so an out-of-range span that
		// moved it would silently swallow every later span in its list — a worse
		// failure than the scrambling the guard exists for (found in review).
		const doc = description({
			text: 'Uses ~ ax-1 and ~ ax-2 now.',
			references: [
				reference({ target: 'ax-1', start: 5, end: 999 }),
				reference({ target: 'ax-2', start: 16, end: 22 })
			]
		});

		expect(
			renderProse(doc).map((s) =>
				s.kind === 'text' ? s.text : s.kind === 'citation' ? s.citation.work : s.reference.target
			)
		).toEqual(['Uses ~ ax-1 and ', 'ax-2', ' now.']);
	});

	it('does the same for a citation', () => {
		const doc = description({
			text: 'From [A] p. 1 and [B] p. 2.',
			citations: [
				{ work: 'A', page: '1', start: 5, end: 999 },
				{ work: 'B', page: '2', start: 18, end: 26 }
			]
		});

		expect(renderProse(doc).map((s) => s.kind)).toEqual(['text', 'citation', 'text']);
	});
});
