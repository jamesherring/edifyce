import type { FormalSystemDetail, Rule } from '$lib/api';

/** One line of the notation reference: what to write, and what it stands for. */
export interface NotationEntry {
	form: string;
	detail: string;
}

export interface NotationGroup {
	title: string;
	entries: NotationEntry[];
}

/** How a production is written, in the grammar's own terms. */
function productionForm(production: FormalSystemDetail['productions'][number]): string {
	if (production.template !== null) return production.template;
	if (production.atom_value !== null) return production.atom_value;
	if (production.atom_base !== null) return `${production.atom_base}_#`;
	return `/${production.regex ?? ''}/`;
}

/**
 * A rule written as `premises ⊢ conclusion`.
 *
 * A discharge rule (→I, RAA, ∀I) cites no lines — the subproof it consumes *is*
 * its premise — so writing only its (empty) antecedents would render it as a
 * zero-premise rule. Its subproof is shown instead, in the engine's own
 * `assume`/`fresh` vocabulary: `[assume p ⊢ q] ⊢ (p → q)`.
 */
export function ruleShape(rule: Rule): string {
	const sub = rule.subproof;
	let premises: string;
	if (sub) {
		// The backend sets exactly one of `assume`/`fresh`; the type allows both to
		// be null, so fall back to the bare subproof rather than print "assume null".
		const opener =
			sub.fresh !== null ? `fresh ${sub.fresh}` : sub.assume !== null ? `assume ${sub.assume}` : '';
		premises = `[${opener ? `${opener} ⊢ ` : ''}${sub.derive}]`;
	} else {
		premises = rule.antecedents.join(' ; ') || '—';
	}
	return `${premises} ⊢ ${rule.deduction}`;
}

/**
 * The grammar an author is writing against, as a reference to show beside a part
 * form. This is what the system already knows and the author would otherwise
 * have to hold in their head (or close the sheet to go and look up).
 */
export function notationReference(system: FormalSystemDetail | null | undefined): NotationGroup[] {
	if (!system) return [];
	const groups: NotationGroup[] = [
		{
			title: 'Sorts',
			entries: system.sorts.map((s) => ({ form: s.name, detail: '' }))
		},
		{
			title: 'Brackets',
			entries: system.brackets.map((b) => ({ form: `${b.opening} ${b.closing}`, detail: '' }))
		},
		{
			title: 'Grammar',
			entries: system.productions.map((p) => ({
				form: productionForm(p),
				detail: `${p.name} : ${p.sort}`
			}))
		},
		{
			title: 'Definitions',
			entries: system.definitions.map((d) => ({ form: d.higher, detail: d.name }))
		},
		{
			title: 'Rules',
			entries: system.rules.map((r) => ({ form: ruleShape(r), detail: r.label }))
		}
	];
	return groups.filter((group) => group.entries.length > 0);
}
