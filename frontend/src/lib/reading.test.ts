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

	it('restores the indentation a subproof was written with', () => {
		expect(readProofLine(line({ indent: 1 }))).toBe('    x ≡ x [HYP]');
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
