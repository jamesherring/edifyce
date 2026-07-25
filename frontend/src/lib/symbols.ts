import type { FormalSystemDetail } from '$lib/api';

/** One insertable token and the name shown in its tooltip. */
export interface SymbolEntry {
	char: string;
	name: string;
}

export interface SymbolGroup {
	title: string;
	symbols: SymbolEntry[];
}

function entries(pairs: [string, string][]): SymbolEntry[] {
	return pairs.map(([char, name]) => ({ char, name }));
}

/**
 * The standing catalogue of notation offered by the symbol palette. Groups are
 * disjoint so a character appears exactly once in the picker, and every entry is
 * a character no keyboard types directly — ASCII that users can already type
 * (`=`, `<`, `(`) is deliberately absent.
 */
export const SYMBOL_GROUPS: SymbolGroup[] = [
	{
		title: 'Logic',
		symbols: entries([
			['¬', 'not'],
			['∧', 'and'],
			['∨', 'or'],
			['→', 'implies'],
			['↔', 'if and only if'],
			['⊕', 'exclusive or'],
			['⊤', 'true'],
			['⊥', 'false'],
			['⊢', 'proves (turnstile)'],
			['⊨', 'entails'],
			['≡', 'equivalent to'],
			['∴', 'therefore'],
			['∀', 'for all'],
			['∃', 'there exists'],
			['∄', 'there does not exist'],
			['□', 'necessarily'],
			['◇', 'possibly'],
		])
	},
	{
		title: 'Sets',
		symbols: entries([
			['∈', 'is a member of'],
			['∉', 'is not a member of'],
			['⊆', 'is a subset of'],
			['⊂', 'is a proper subset of'],
			['⊇', 'is a superset of'],
			['⊃', 'is a proper superset of'],
			['∪', 'union'],
			['∩', 'intersection'],
			['∖', 'set difference'],
			['∅', 'empty set'],
			['℘', 'power set'],
			['×', 'cartesian product'],
			['⋃', 'union over'],
			['⋂', 'intersection over'],
		])
	},
	{
		title: 'Relations',
		symbols: entries([
			['≠', 'is not equal to'],
			['≤', 'is less than or equal to'],
			['≥', 'is greater than or equal to'],
			['≈', 'is approximately equal to'],
			['≅', 'is congruent to'],
			['≺', 'precedes'],
			['≼', 'precedes or equals'],
			['≻', 'succeeds'],
			['∼', 'is similar to'],
			['≝', 'is defined as'],
			['∣', 'divides'],
			['∤', 'does not divide'],
		])
	},
	{
		title: 'Arrows',
		symbols: entries([
			['←', 'leftwards arrow'],
			['⇒', 'double implies'],
			['⇐', 'double implied by'],
			['⇔', 'double if and only if'],
			['↦', 'maps to'],
			['⟶', 'long rightwards arrow'],
			['⟵', 'long leftwards arrow'],
			['⟹', 'long double implies'],
		])
	},
	{
		title: 'Brackets',
		symbols: entries([
			['⟨', 'left angle bracket'],
			['⟩', 'right angle bracket'],
			['⌜', 'left corner quote'],
			['⌝', 'right corner quote'],
			['⟦', 'left double bracket'],
			['⟧', 'right double bracket'],
			['⌊', 'left floor'],
			['⌋', 'right floor'],
			['⌈', 'left ceiling'],
			['⌉', 'right ceiling'],
		])
	},
	{
		title: 'Greek',
		symbols: entries([
			['α', 'alpha'],
			['β', 'beta'],
			['γ', 'gamma'],
			['δ', 'delta'],
			['ε', 'epsilon'],
			['ζ', 'zeta'],
			['η', 'eta'],
			['θ', 'theta'],
			['ι', 'iota'],
			['κ', 'kappa'],
			['λ', 'lambda'],
			['μ', 'mu'],
			['ν', 'nu'],
			['ξ', 'xi'],
			['π', 'pi'],
			['ρ', 'rho'],
			['σ', 'sigma'],
			['τ', 'tau'],
			['φ', 'phi'],
			['χ', 'chi'],
			['ψ', 'psi'],
			['ω', 'omega'],
			['Γ', 'capital gamma'],
			['Δ', 'capital delta'],
			['Θ', 'capital theta'],
			['Λ', 'capital lambda'],
			['Ξ', 'capital xi'],
			['Π', 'capital pi'],
			['Σ', 'capital sigma'],
			['Φ', 'capital phi'],
			['Ψ', 'capital psi'],
			['Ω', 'capital omega'],
		])
	},
	{
		title: 'Other',
		symbols: entries([
			['∘', 'composed with'],
			['⋅', 'dot operator'],
			['∞', 'infinity'],
			['ℕ', 'natural numbers'],
			['ℤ', 'integers'],
			['ℚ', 'rationals'],
			['ℝ', 'reals'],
			['ℂ', 'complex numbers'],
			['⋯', 'ellipsis'],
			['∎', 'end of proof'],
		])
	},
];

const CATALOGUE_NAMES = new Map<string, string>(
	SYMBOL_GROUPS.flatMap((group) => group.symbols.map((s) => [s.char, s.name] as [string, string]))
);

/** The catalogue name for a character, or the character itself if it isn't one. */
export function symbolName(char: string): string {
	return CATALOGUE_NAMES.get(char) ?? char;
}

/** The notation-bearing strings of a system — the fields whose content is object
 *  syntax, not prose. Names and descriptions are deliberately excluded. */
function notationStrings(system: FormalSystemDetail): string[] {
	const out: string[] = [];
	for (const b of system.brackets) out.push(b.opening, b.closing);
	for (const p of system.productions) {
		out.push(p.template ?? '', p.regex ?? '', p.atom_value ?? '', p.atom_base ?? '');
	}
	for (const l of system.lines) out.push(l.shape);
	for (const d of system.definitions) out.push(d.higher, d.lower, d.label ?? '', ...d.provisos);
	for (const a of system.axioms) out.push(a.label, a.formula);
	for (const r of system.rules) {
		out.push(r.label, r.deduction, ...r.antecedents, ...r.side_conditions);
		if (r.subproof) out.push(r.subproof.derive, r.subproof.assume ?? '', r.subproof.fresh ?? '');
	}
	return out;
}

/** How many of a system's own symbols the palette offers as its quick row. */
const SYSTEM_SYMBOL_LIMIT = 16;

/**
 * The non-ASCII characters a system's own notation uses, most-used first. These
 * are the symbols an author of *this* system actually needs, so the palette
 * leads with them and keeps the full catalogue a click away. Ranking by use
 * frequency (ties broken by first appearance) keeps the row stable as a system
 * grows rather than reshuffling on every edit.
 */
export function systemSymbols(system: FormalSystemDetail | null | undefined): SymbolEntry[] {
	if (!system) return [];
	const counts = new Map<string, number>();
	for (const text of notationStrings(system)) {
		// Iterate by code point so astral characters (𝒫, ℬ) stay intact.
		for (const char of Array.from(text)) {
			if (char.codePointAt(0)! <= 0x7f) continue;
			counts.set(char, (counts.get(char) ?? 0) + 1);
		}
	}
	// A Map keeps insertion order, so its key order *is* first-appearance order;
	// snapshot it as ranks before sorting (which would otherwise reorder it).
	const firstSeen = new Map([...counts.keys()].map((char, i) => [char, i] as [string, number]));
	return [...counts.keys()]
		.sort((a, b) => counts.get(b)! - counts.get(a)! || firstSeen.get(a)! - firstSeen.get(b)!)
		.slice(0, SYSTEM_SYMBOL_LIMIT)
		.map((char) => ({ char, name: symbolName(char) }));
}
