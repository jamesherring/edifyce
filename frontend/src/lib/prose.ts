import type { BibliographyCitation, LabelDescription, LabelReference } from '$lib/api';

/** One piece of a description's prose: plain text, a cross-reference, or a
 * bibliography citation. The last two are both spans the API sends offsets for;
 * they differ in where they point — inside the corpus, or out of it. */
export type ProseSegment =
	| { kind: 'text'; text: string }
	| { kind: 'reference'; reference: LabelReference }
	| { kind: 'citation'; citation: BibliographyCitation };

type Span = { start: number; end: number; segment: ProseSegment };

/** One list's spans, in the order it sent them, with anything unusable gone.
 *
 * Applied per list rather than to the merged whole, which matters: the API sends
 * each list in document order, so a span that starts before the previous one
 * ended is the anomalous one and the earlier is what the prose meant. Sorting the
 * two lists together first would let a corrupt row *win* by starting earlier —
 * exactly the scrambling the drop exists to prevent (found when the merge
 * regressed the test written for it).
 *
 * `length` is the prose's, and a span past the end is dropped **without moving
 * the cursor** — otherwise one out-of-range row poisons every later span in its
 * list, which is a worse failure than the one this guards (found in review). */
function ordered(spans: Span[], length: number): Span[] {
	const kept: Span[] = [];
	let cursor = 0;
	for (const span of spans) {
		if (span.start < cursor || span.end > length) continue;
		kept.push(span);
		cursor = span.end;
	}
	return kept;
}

/** Two already-ordered lists interleaved by position.
 *
 * A merge rather than a sort, so each list keeps its own order where the two
 * start at the same offset — which nothing should produce, since a reference and
 * a citation are different characters, but which must not scramble if it does. */
function merge(references: Span[], citations: Span[]): Span[] {
	const merged: Span[] = [];
	let left = 0;
	let right = 0;
	while (left < references.length && right < citations.length) {
		merged.push(
			references[left].start <= citations[right].start
				? references[left++]
				: citations[right++]
		);
	}
	return [...merged, ...references.slice(left), ...citations.slice(right)];
}

/**
 * Split a description's prose into what to print, what to link, and what to cite.
 *
 * The offsets do the work. A Metamath comment writes a cross-reference as
 * `~ label` and a citation as `[Monk1] p. 22`, and the rules for reading them —
 * where a target ends, what `~~` and `[[` mean, which brackets are mathematics
 * rather than a source — live in the engine, which is where the file is. The API
 * sends the span each occupies, so this slices; it does not parse. That is
 * deliberate: a second implementation of the markup here would be a second thing
 * to keep in step with a corpus of 21,787 references and 5,271 citations.
 *
 * The two lists are merged by position rather than concatenated, since they
 * interleave — `Theorem 3.1 of [Monk1] p. 22; see also ~ ax-1` is a citation then
 * a reference, and either may come first.
 *
 * Defensive about the offsets only where being wrong would be silent: a span
 * outside the text, or overlapping the one before it, is dropped rather than
 * allowed to reorder or duplicate the prose. Nothing should produce one — they
 * are written by the same pass that assembled the text — but a stale row
 * surviving a schema change should degrade to plain prose, not to scrambled
 * prose. An overlap between the two *kinds* is the new case, and it is dropped by
 * the same rule.
 */
export function renderProse(description: LabelDescription): ProseSegment[] {
	const length = description.text.length;
	const spans: Span[] = merge(
		ordered(
			description.references.map((reference) => ({
				start: reference.start,
				end: reference.end,
				segment: { kind: 'reference', reference } as const
			})),
			length
		),
		ordered(
			description.citations.map((citation) => ({
				start: citation.start,
				end: citation.end,
				segment: { kind: 'citation', citation } as const
			})),
			length
		)
	);

	const segments: ProseSegment[] = [];
	let cursor = 0;
	for (const span of spans) {
		if (span.start < cursor) continue;
		if (span.start > cursor) {
			segments.push({ kind: 'text', text: description.text.slice(cursor, span.start) });
		}
		segments.push(span.segment);
		cursor = span.end;
	}
	if (cursor < description.text.length) {
		segments.push({ kind: 'text', text: description.text.slice(cursor) });
	}
	return segments;
}

/** Where a reference points, or null when it points nowhere this app can reach.
 *
 * A proof of this system wins: it is the page that shows the statement, its lines
 * and its own documentation. Failing that, an absolute URL is followed as written
 * — 242 of set.mm's references are papers and 32 are pages of the Metamath site. A
 * bare label with no proof (a definition, an axiom) has nowhere to go yet. */
export function referenceHref(reference: LabelReference): string | null {
	if (reference.proof_id) return `/proofs/${reference.proof_id}`;
	if (/^https?:\/\//.test(reference.target)) return reference.target;
	return null;
}
