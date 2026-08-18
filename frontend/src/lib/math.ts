/**
 * Typesetting a reading that is TeX rather than text.
 *
 * A system's notations are stored server-side and served by name (`unicode`,
 * `latex`), and what comes back for a line is a *string* either way — the
 * projection folds one template per production over the term, and whether the
 * result is meant to be read or to be set as mathematics is a fact about the
 * notation, not about the line.
 *
 * So the name is what decides it, which is the same judgement the import makes
 * when it derives a projection from a `.mm` file's `$t` block: `latexdef` becomes
 * the notation called `latex` (`website/logical/metamath/display.py`). A notation
 * an author names `latex` themselves is taken at its word.
 */

import katex from 'katex';

/** Whether a notation's readings are TeX source rather than text to show. */
export function isTeX(notation: string | null): boolean {
	return notation === 'latex';
}

/**
 * The notation to open a proof of this system in, or null for its source.
 *
 * The system's own setting wins where it names a notation the system still has —
 * a stored default outlives the notation it names, since the two are edited
 * apart. Otherwise typeset mathematics is the friendlier read, so a system
 * carrying a TeX notation opens in it; a system with none opens in its source.
 */
export function preferredNotation(
	notations: string[],
	defaultNotation: string | null
): string | null {
	if (defaultNotation && notations.includes(defaultNotation)) return defaultNotation;
	return notations.find(isTeX) ?? null;
}

/**
 * `tex` as KaTeX markup, or null when KaTeX will not parse it.
 *
 * Null rather than KaTeX's own error rendering: a projection is derived per
 * production from a token map nobody checked against a TeX parser, so a line
 * that will not typeset is expected rather than exceptional, and the useful
 * fallback is the source it was going to be set from. `\color{red}` over a whole
 * proof line would say "this proof is wrong", which is not what happened.
 *
 * KaTeX escapes what it emits and `trust` is off by default, so no `\href` or
 * raw HTML can come out of a stored template.
 */
export function typeset(tex: string): string | null {
	try {
		return katex.renderToString(tex, { throwOnError: true, displayMode: false });
	} catch {
		return null;
	}
}
