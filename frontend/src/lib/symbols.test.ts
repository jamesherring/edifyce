import { describe, expect, it } from 'vitest';
import { SYMBOL_GROUPS, symbolName, systemSymbols } from './symbols';
import type { Axiom, Definition, FormalSystemDetail, Production, Rule } from './api';

function system(parts: Partial<FormalSystemDetail> = {}): FormalSystemDetail {
	return {
		id: 'sys-1',
		name: 'Test system',
		slug: 'test-system',
		description: null,
		inherits_from_id: null,
		token_separated: false,
		published_at: null,
		created_at: '2026-01-01T00:00:00Z',
		updated_at: '2026-01-01T00:00:00Z',
		owner: null,
		brackets: [],
		sorts: [],
		productions: [],
		lines: [],
		definitions: [],
		axioms: [],
		rules: [],
		...parts
	};
}

function production(template: string): Production {
	return {
		id: `p-${template}`,
		name: template,
		sort: 'formula',
		kind: 'composite',
		template,
		regex: null,
		atom_value: null,
		atom_base: null,
		denotes_constant: false,
		bindings: []
	};
}

function axiom(formula: string): Axiom {
	return { id: `a-${formula}`, label: 'AX', name: 'axiom', formula, bindings: [] };
}

function rule(deduction: string, antecedents: string[] = []): Rule {
	return {
		id: `r-${deduction}`,
		label: 'R',
		name: 'rule',
		deduction,
		antecedents,
		bindings: [],
		side_conditions: [],
		matching: 'structural',
		subproof: null,
		allow_extra_antecedents: false
	};
}

function definition(higher: string, lower: string): Definition {
	return {
		id: `d-${higher}`,
		sort: 'formula',
		name: 'def',
		higher,
		lower,
		provisos: [],
		condition: null,
		bindings: [],
		fresh: [],
		label: null
	};
}

describe('SYMBOL_GROUPS', () => {
	it('lists every character exactly once across groups', () => {
		const all = SYMBOL_GROUPS.flatMap((g) => g.symbols.map((s) => s.char));
		expect(all).toHaveLength(new Set(all).size);
	});

	it('offers only characters a keyboard cannot type directly', () => {
		const ascii = SYMBOL_GROUPS.flatMap((g) => g.symbols)
			.map((s) => s.char)
			.filter((c) => c.codePointAt(0)! <= 0x7f);
		expect(ascii).toEqual([]);
	});
});

describe('symbolName', () => {
	it('names a catalogued character', () => {
		expect(symbolName('∀')).toBe('for all');
	});

	it('falls back to the character itself for anything else', () => {
		expect(symbolName('❖')).toBe('❖');
	});
});

describe('systemSymbols', () => {
	it('returns nothing without a system', () => {
		expect(systemSymbols(null)).toEqual([]);
	});

	it('collects the non-ASCII notation a system declares, and nothing else', () => {
		const symbols = systemSymbols(
			system({ productions: [production('(p → q)')], axioms: [axiom('∀x x = x')] })
		);
		// The ASCII in those strings (p, q, x, =, parens) is already typeable.
		expect(symbols.map((s) => s.char)).toEqual(['→', '∀']);
	});

	it('names catalogued characters and leaves unknown ones as themselves', () => {
		const symbols = systemSymbols(system({ axioms: [axiom('x ⊆ y'), axiom('x ❖ y')] }));
		expect(symbols).toEqual([
			{ char: '⊆', name: 'is a subset of' },
			{ char: '❖', name: '❖' }
		]);
	});

	it('ranks by how often the notation uses each symbol', () => {
		// → is seen first but used once; ∧ twice, so ∧ leads.
		const symbols = systemSymbols(
			system({
				productions: [production('(p → q)')],
				rules: [rule('(p ∧ q)', ['p ∧ q'])]
			})
		);
		expect(symbols.map((s) => s.char)).toEqual(['∧', '→']);
	});

	it('reads both halves of a definition — the defined form and its expansion', () => {
		const symbols = systemSymbols(
			system({ definitions: [definition('x ⊆ y', '∀z (z ∈ x → z ∈ y)')] })
		);
		// ∈ is used twice; the singletons then follow in first-seen order.
		expect(symbols.map((s) => s.char)).toEqual(['∈', '⊆', '∀', '→']);
	});

	it('breaks ties by first appearance, so the row does not reshuffle', () => {
		const symbols = systemSymbols(system({ axioms: [axiom('α'), axiom('β'), axiom('γ')] }));
		expect(symbols.map((s) => s.char)).toEqual(['α', 'β', 'γ']);
	});

	it('caps the quick row so a large system cannot flood it', () => {
		const wide = Array.from({ length: 40 }, (_, i) => axiom(String.fromCodePoint(0x3b1 + i)));
		expect(systemSymbols(system({ axioms: wide }))).toHaveLength(16);
	});
});
