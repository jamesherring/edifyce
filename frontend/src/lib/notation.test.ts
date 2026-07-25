import { describe, expect, it } from 'vitest';
import { notationReference, rulePremises, ruleShape } from './notation';
import type { FormalSystemDetail, Production, Rule } from './api';

function system(parts: Partial<FormalSystemDetail> = {}): FormalSystemDetail {
	return {
		id: 'sys-1',
		name: 'Test system',
		slug: 'test-system',
		description: null,
		inherits_from_id: null,
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

function production(over: Partial<Production> = {}): Production {
	return {
		id: 'p-1',
		name: 'implication',
		sort: 'formula',
		kind: 'composite',
		template: null,
		regex: null,
		atom_value: null,
		atom_base: null,
		bindings: [],
		...over
	};
}

function rule(over: Partial<Rule> = {}): Rule {
	return {
		id: 'r-1',
		label: 'MP',
		name: 'modus ponens',
		deduction: 'q',
		antecedents: [],
		bindings: [],
		side_conditions: [],
		matching: 'structural',
		subproof: null,
		allow_extra_antecedents: false,
		...over
	};
}

describe('ruleShape', () => {
	it('writes a line-antecedent rule as premises ⊢ conclusion', () => {
		expect(ruleShape(rule({ antecedents: ['p', '(p → q)'] }))).toBe('p ; (p → q) ⊢ q');
	});

	it('marks a rule with no premises rather than leaving the left side blank', () => {
		expect(ruleShape(rule({ deduction: 'p' }))).toBe('— ⊢ p');
	});

	it('shows the subproof a discharge rule consumes — it is the premise', () => {
		// Without this, →I renders as "— ⊢ (p → q)" and reads as a zero-premise rule.
		const impliesIntro = rule({
			label: '→I',
			deduction: '(p → q)',
			subproof: { derive: 'q', assume: 'p', fresh: null }
		});
		expect(ruleShape(impliesIntro)).toBe('[assume p ⊢ q] ⊢ (p → q)');
	});

	it('exposes the premise side alone, for a table with its own conclusion column', () => {
		// The read-only system detail page splits "From" and "Infer" across cells.
		expect(rulePremises(rule({ antecedents: ['p', '(p → q)'] }))).toBe('p ; (p → q)');
		expect(
			rulePremises(rule({ subproof: { derive: 'q', assume: 'p', fresh: null } }))
		).toBe('[assume p ⊢ q]');
	});

	it('names an eigenvariable subproof by its fresh variable', () => {
		const forallIntro = rule({
			label: '∀I',
			deduction: '∀x φ',
			subproof: { derive: 'φ', assume: null, fresh: 'x' }
		});
		expect(ruleShape(forallIntro)).toBe('[fresh x ⊢ φ] ⊢ ∀x φ');
	});
});

function titles(system: FormalSystemDetail) {
	return notationReference(system).map((g) => g.title);
}

describe('notationReference', () => {
	it('returns nothing without a system', () => {
		expect(notationReference(null)).toEqual([]);
	});

	it('omits groups the system has nothing in', () => {
		expect(titles(system({ sorts: [{ id: 's', name: 'formula' }] }))).toEqual(['Sorts']);
	});

	it('lists sorts and bracket pairs', () => {
		const groups = notationReference(
			system({
				sorts: [{ id: 's1', name: 'term' }],
				brackets: [{ id: 'b1', opening: '⟨', closing: '⟩' }]
			})
		);
		expect(groups).toEqual([
			{ title: 'Sorts', entries: [{ form: 'term', detail: '' }] },
			{ title: 'Brackets', entries: [{ form: '⟨ ⟩', detail: '' }] }
		]);
	});

	it('writes each production in the form an author would type', () => {
		const groups = notationReference(
			system({
				productions: [
					production({ id: 'a', template: '(p → q)' }),
					production({ id: 'b', name: 'falsum', atom_value: '⊥' }),
					production({ id: 'c', name: 'prop', atom_base: 'p' }),
					production({ id: 'd', name: 'variable', sort: 'term', regex: '[a-z]' })
				]
			})
		);
		expect(groups[0].entries).toEqual([
			{ form: '(p → q)', detail: 'implication : formula' },
			{ form: '⊥', detail: 'falsum : formula' },
			// An indexed family is written with its subscript placeholder…
			{ form: 'p_#', detail: 'prop : formula' },
			// …and a regex is shown delimited, so it isn't mistaken for literal syntax.
			{ form: '/[a-z]/', detail: 'variable : term' }
		]);
	});

	it('shows a definition by its defined form and a rule by its shape', () => {
		const groups = notationReference(
			system({
				definitions: [
					{
						id: 'd1',
						sort: 'formula',
						name: 'subset',
						higher: 'x ⊆ y',
						lower: '∀z (z ∈ x → z ∈ y)',
						provisos: [],
						condition: null,
						bindings: [],
						fresh: [],
						label: null
					}
				],
				rules: [
					rule({ id: 'r1', antecedents: ['p', '(p → q)'] }),
					rule({ id: 'r2', label: 'HYP', deduction: 'p' }),
					rule({
						id: 'r3',
						label: '→I',
						deduction: '(p → q)',
						subproof: { derive: 'q', assume: 'p', fresh: null }
					})
				]
			})
		);
		expect(groups).toEqual([
			{ title: 'Definitions', entries: [{ form: 'x ⊆ y', detail: 'subset' }] },
			{
				title: 'Rules',
				entries: [
					{ form: 'p ; (p → q) ⊢ q', detail: 'MP' },
					// A rule with no premises still needs a left-hand side to read.
					{ form: '— ⊢ p', detail: 'HYP' },
					// A discharge rule's premise is its subproof, not an empty list.
					{ form: '[assume p ⊢ q] ⊢ (p → q)', detail: '→I' }
				]
			}
		]);
	});
});
