import { describe, expect, it } from 'vitest';
import { readProof, readProofLine } from './reading';
import type { ProofStructure, ProofStructureLine } from './api';

function line(over: Partial<ProofStructureLine> = {}): ProofStructureLine {
	return {
		id: 'l-1',
		position: 0,
		number: 1,
		indent: 0,
		display: 'x = x [HYP]',
		line_type: 'statement',
		behaviour: null,
		label: null,
		reference: 'HYP',
		rule: null,
		definition_id: null,
		valid: true,
		invalid_message: null,
		failure: null,
		warning_message: null,
		opens_scope: null,
		scope_id: null,
		term: null,
		rendered: 'x ≡ x',
		antecedents: [],
		...over
	};
}

function structure(over: Partial<ProofStructure> = {}): ProofStructure {
	return { proof_id: 'p-1', stored: true, notation: 'equiv', lines: [line()], ...over };
}

describe('readProofLine', () => {
	it('puts the citation back on the rendered term', () => {
		// The server renders the line's term, which carries no citation - so a
		// reading that showed only `rendered` would silently drop every
		// justification the proof states.
		expect(readProofLine(line())).toBe('x ≡ x [HYP]');
	});

	it('leaves a line with no citation uncited', () => {
		expect(readProofLine(line({ reference: null }))).toBe('x ≡ x');
	});

	it('keeps the source of a line that bears no term', () => {
		// A blank, a comment or a scope opener has nothing to re-spell. Falling back
		// to `display` keeps the proof the same shape in both readings.
		expect(readProofLine(line({ rendered: null, display: '-- lemma', reference: null }))).toBe(
			'-- lemma'
		);
	});

	it('keeps the whole source line, citation included, when it falls back', () => {
		// `display` is the authored line and already carries its citation, so the
		// fallback must not append a second one.
		expect(readProofLine(line({ rendered: null }))).toBe('x = x [HYP]');
	});

	it('falls back when the notation names nothing for the line', () => {
		// A notation missing the line's constructor renders empty rather than null
		// (the server distinguishes "not asked for" from "nothing to say"), and an
		// empty formula with a citation hung off it is worse than the source.
		expect(readProofLine(line({ rendered: '' }))).toBe('x = x [HYP]');
	});

	it('restores the indentation a subproof was written with', () => {
		// `indent` is a count of leading *spaces*, which is how the server rebuilds
		// the source line too — not a nesting depth to expand.
		expect(readProofLine(line({ indent: 4 }))).toBe('    x ≡ x [HYP]');
	});
});

describe('readProof', () => {
	it('joins the lines in order', () => {
		const read = readProof(
			structure({
				lines: [line({ id: 'a' }), line({ id: 'b', rendered: '(x ≡ x → x ≡ x)', reference: 'MP' })]
			})
		);
		expect(read).toBe('x ≡ x [HYP]\n(x ≡ x → x ≡ x) [MP]');
	});

	it('reads nothing when no structure is stored', () => {
		// Null, not "": a proof that was never checked has no terms to project, and
		// the caller must say so rather than show an empty proof.
		expect(readProof(structure({ stored: false, lines: [] }))).toBeNull();
		expect(readProof(null)).toBeNull();
	});
});
