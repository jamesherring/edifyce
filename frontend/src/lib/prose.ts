import type { LabelDescription, LabelReference } from '$lib/api';

/** One piece of a description's prose: either plain text or a cross-reference. */
export type ProseSegment =
	| { kind: 'text'; text: string }
	| { kind: 'reference'; reference: LabelReference };

/**
 * Split a description's prose into what to print and what to link.
 *
 * The offsets do the work. A Metamath comment writes a cross-reference as
 * `~ label`, and the rule for reading one — where it ends, what `~~` means — lives
 * in the engine, which is where the file is. The API sends the span each reference
 * occupies, so this slices; it does not parse. That is deliberate: a second
 * implementation of the markup here would be a second thing to keep in step with
 * a corpus of 21,787 of them.
 *
 * Defensive about the offsets only where being wrong would be silent: a reference
 * outside the text, or overlapping the one before it, is dropped rather than
 * allowed to reorder or duplicate the prose. Nothing should produce one — they are
 * written by the same pass that assembled the text — but a stale row surviving a
 * schema change should degrade to plain prose, not to scrambled prose.
 */
export function renderProse(description: LabelDescription): ProseSegment[] {
	const segments: ProseSegment[] = [];
	let cursor = 0;
	for (const reference of description.references) {
		if (reference.start < cursor || reference.end > description.text.length) continue;
		if (reference.start > cursor) {
			segments.push({ kind: 'text', text: description.text.slice(cursor, reference.start) });
		}
		segments.push({ kind: 'reference', reference });
		cursor = reference.end;
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
