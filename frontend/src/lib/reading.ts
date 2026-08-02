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
 * A line the notation cannot read keeps the source it was written in, whole: a
 * line bearing no term (a blank, a comment, a scope opener) has nothing to
 * re-spell, and one whose constructor the notation does not name renders empty.
 * `display` already carries its own citation, so the two cases are one — either
 * the term was read and this writes the citation, or the source line stands as
 * the author wrote it.
 */
export function readProofLine(line: ProofStructureLine): string {
	// Indentation is a count of leading spaces (`ProofLine.indent`), which is how
	// the source line is reconstructed server-side too.
	const indent = ' '.repeat(line.indent);
	if (!line.rendered) return indent + line.display;
	return indent + (line.reference ? `${line.rendered} [${line.reference}]` : line.rendered);
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
