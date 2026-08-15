/**
 * Reading a checked proof through one of its system's notations.
 *
 * The rows a proof is shown as come from its **stored structure**, not from the
 * cached verification payload: a notation re-spells *terms*, and the structure is
 * where a term lives beside the checker's verdict on the line holding it. That is
 * the whole of why the notation switch reaches the checked view — one row carries
 * both.
 *
 * What the server renders is narrower than the line the author wrote: it is the
 * term alone, so it carries no citation and no indentation. Both are structure
 * the checker stored separately, and the row puts them back.
 */

import type { ProofLine, ProofStructure, ProofStructureLine } from '$lib/api';

/**
 * A line ready to display: the verification payload's shape, plus whether its
 * `display` is the notation's reading or the source it was written in.
 *
 * The flag is what a TeX reading needs. A notation re-spells terms, so a line
 * bearing none keeps its source however the reading is set — and handing that
 * source to a typesetter would set an author's prose as mathematics.
 */
export type ReadLine = ProofLine & {
	typeset: boolean;
	/** The rule the checker resolved this line's citation to, where the rows say.
	 *  What a citation's card is looked up by — the citation text is the author's
	 *  spelling and may name lines beside the label. Null for a row that carries
	 *  none, and for every line of the cached payload, which stores no such field. */
	rule: string | null;
};

/** The verification payload's own lines, which are always the source spelling. */
export function resultLines(lines: ProofLine[]): ReadLine[] {
	return lines.map((line) => ({ ...line, typeset: false, rule: null }));
}

/**
 * What a line reads as, and whether that is the notation talking.
 *
 * Empty counts as nothing to say, not as an empty formula: the server
 * distinguishes "no notation asked for" (null) from "this notation names the
 * line's constructor nothing" (`''`), and a blank row where a formula was is
 * worse than the source in the wrong spelling.
 */
function reading(line: ProofStructureLine): { display: string; typeset: boolean } {
	if (!line.rendered) return { display: line.display, typeset: false };
	return { display: line.rendered, typeset: true };
}

/**
 * The stored structure as display rows, or null when nothing is stored.
 *
 * Null rather than an empty list: a proof never checked, or checked before this
 * store existed, has no rows to show and a caller should fall back to its source
 * rather than render an empty proof.
 */
export function readLines(structure: ProofStructure | null): ReadLine[] | null {
	if (!structure || !structure.stored) return null;
	return structure.lines.map((line) => ({
		valid: line.valid,
		number: line.number,
		behaviour: line.behaviour,
		// The matched line type's name — `ProofLine.name` under another spelling,
		// since the row stores what the checker determined and the payload stores
		// what it displayed.
		name: line.line_type,
		invalid_message: line.invalid_message,
		failure: line.failure,
		warning_message: line.warning_message,
		reference: line.reference,
		rule: line.rule,
		label: line.label,
		indent: line.indent,
		...reading(line)
	}));
}
