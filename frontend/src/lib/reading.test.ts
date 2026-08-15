import { describe, expect, it } from 'vitest';
import { readLines, resultLines } from './reading';
import type { ProofLine, ProofStructure, ProofStructureLine } from './api';

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

describe('readLines', () => {
	it('shows the term the notation re-spelled', () => {
		const [row] = readLines(structure())!;

		expect(row.display).toBe('x ≡ x');
		expect(row.typeset).toBe(true);
	});

	it('carries the checker’s verdict on the same row as the reading', () => {
		// The point of reading the structure rather than the verification payload:
		// a re-spelled line and the diagnostics about it are one row, so a notation
		// cannot leave the two disagreeing.
		const [row] = readLines(
			structure({
				lines: [line({ valid: false, invalid_message: 'MP does not apply.', number: 3 })]
			})
		)!;

		expect(row.valid).toBe(false);
		expect(row.invalid_message).toBe('MP does not apply.');
		expect(row.number).toBe(3);
		expect(row.reference).toBe('HYP');
	});

	it('keeps the source of a line that bears no term', () => {
		// A blank, a comment or a scope opener has nothing to re-spell, and its
		// source is not mathematics to typeset.
		const [row] = readLines(
			structure({ lines: [line({ rendered: null, display: '-- lemma', reference: null })] })
		)!;

		expect(row).toMatchObject({ display: '-- lemma', typeset: false });
	});

	it('falls back when the notation names nothing for the line', () => {
		// The server distinguishes "not asked for" (null) from "nothing to say"
		// (empty), and a blank row where a formula was is worse than the source.
		const [row] = readLines(structure({ lines: [line({ rendered: '' })] }))!;

		expect(row).toMatchObject({ display: 'x = x [HYP]', typeset: false });
	});

	it('keeps the line type under the name the payload gives it', () => {
		// `ProofLine.name` is the matched line type, which the row stores as
		// `line_type`; the badge reads one field whichever source the rows came from.
		const [row] = readLines(structure({ lines: [line({ line_type: 'Derivation' })] }))!;

		expect(row.name).toBe('Derivation');
	});

	it('reads nothing when no structure is stored', () => {
		// Null, not an empty list: a proof never checked has nothing to show, and
		// the caller falls back to its source rather than rendering an empty proof.
		expect(readLines(structure({ stored: false, lines: [] }))).toBeNull();
		expect(readLines(null)).toBeNull();
	});
});

describe('resultLines', () => {
	it('never claims the payload is a notation’s reading', () => {
		// `ProofDetail.result` is the source spelling by construction — it is what
		// the checker displayed — so nothing in it is TeX to typeset.
		const payload: ProofLine = {
			valid: true,
			number: 1,
			behaviour: null,
			name: 'statement',
			invalid_message: null,
			warning_message: null,
			reference: 'HYP',
			label: null,
			display: 'x = x',
			indent: 0
		};

		// `rule` too: the payload records what the checker *displayed*, not what it
		// resolved, so there is no label to look a citation's card up by.
		expect(resultLines([payload])).toEqual([{ ...payload, typeset: false, rule: null }]);
	});
});

describe('the rule a citation resolved to', () => {
	it('comes off the row, not out of the citation text', () => {
		// `[MP, 1, 2]` is the author's spelling and names lines beside the label;
		// the row records what the checker resolved, which is what a card is
		// looked up by.
		const [row] = readLines(structure({ lines: [line({ rule: 'MP', reference: 'MP, 1, 2' })] }))!;

		expect(row.rule).toBe('MP');
		expect(row.reference).toBe('MP, 1, 2');
	});
});
