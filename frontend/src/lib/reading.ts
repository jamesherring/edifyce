/**
 * Reading a checked proof through one of its system's notations.
 *
 * The server renders each line's *term* — that is what a notation re-spells — so
 * what comes back is narrower than the line the author wrote: no citation, no
 * indentation. Both are structure the checker already stored separately, so this
 * puts them back rather than asking the server for a second rendering of them.
 */

import type { ProofStructure, ProofStructureLine } from '$lib/api';

/** One line as the chosen notation reads it, indent and citation restored.
 *
 * A line bearing no term — a blank, a comment, a scope opener — has nothing to
 * re-spell and keeps the source it was written in, so a reading is never missing
 * lines the proof has.
 */
export function readProofLine(line: ProofStructureLine): string {
	const body = line.rendered ?? line.display;
	const cited = line.reference ? `${body} [${line.reference}]` : body;
	return '    '.repeat(line.indent) + cited;
}

/** The whole proof read that way, or null when there is nothing stored to read.
 *
 * Null rather than an empty string: a proof checked before the structure store
 * existed, or never checked at all, has no terms to project, and a caller should
 * say so rather than show a blank page where the proof was.
 */
export function readProof(structure: ProofStructure | null): string | null {
	if (!structure || !structure.stored) return null;
	return structure.lines.map(readProofLine).join('\n');
}
