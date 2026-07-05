// Token maps for the four homepage design mockups. Each design reskins the whole
// app by overriding the design tokens on a wrapping element — so the existing
// Button / Card / Badge / Alert components restyle with no per-component changes.
//
// app.css defines the source tokens (`--primary`, `--background`, …) on :root and
// `.dark`, and `@theme inline` wires Tailwind utilities to reference those source
// vars directly (e.g. `bg-primary` → `var(--primary)`). A couple of hand-written
// rules instead use the mapped names (e.g. `* { border-color: var(--color-border) }`).
// To cover both, `designStyle` emits each token under BOTH names: `--<name>` and
// `--color-<name>`.

export type DesignKey = '1' | '3' | '6' | '8';

export interface Design {
	key: DesignKey;
	name: string;
	area: string;
	motif: 'penrose' | 'chalk' | 'golden' | 'cardioid';
	font: string;
	/** Semantic token values, keyed without a leading `--` or `--color-`. */
	tokens: Record<string, string>;
}

const SERIF =
	"'Latin Modern Roman','CMU Serif','Computer Modern','STIX Two Text',Cambria,Georgia,'Times New Roman',serif";

export const DESIGNS: Record<DesignKey, Design> = {
	'1': {
		key: '1',
		name: 'Penrose & Computer Modern',
		area: 'Aperiodic tilings',
		motif: 'penrose',
		font: SERIF,
		tokens: {
			background: '#faf7f0',
			foreground: '#1c1b18',
			card: '#fffdf8',
			'card-foreground': '#1c1b18',
			popover: '#fffdf8',
			'popover-foreground': '#1c1b18',
			primary: '#7c2d2d',
			'primary-foreground': '#faf7f0',
			secondary: '#efe9dc',
			'secondary-foreground': '#1c1b18',
			muted: '#efe9dc',
			'muted-foreground': '#6e655a',
			accent: '#ece4d3',
			'accent-foreground': '#1c1b18',
			destructive: '#b4432f',
			'destructive-foreground': '#faf7f0',
			success: '#4b7b52',
			'success-foreground': '#faf7f0',
			warning: '#b8862f',
			'warning-foreground': '#1c1b18',
			border: '#e0d6c4',
			input: '#e0d6c4',
			ring: '#7c2d2d'
		}
	},
	'3': {
		key: '3',
		name: 'Blackboard',
		area: 'Chalk & slate',
		motif: 'chalk',
		font: SERIF,
		tokens: {
			background: '#20302a',
			foreground: '#edeae2',
			card: '#26362f',
			'card-foreground': '#edeae2',
			popover: '#26362f',
			'popover-foreground': '#edeae2',
			primary: '#e4c766',
			'primary-foreground': '#20302a',
			secondary: '#2e3e37',
			'secondary-foreground': '#edeae2',
			muted: '#2e3e37',
			'muted-foreground': '#9fb0a6',
			accent: '#33453d',
			'accent-foreground': '#edeae2',
			destructive: '#e08a7a',
			'destructive-foreground': '#20302a',
			success: '#a9c7a0',
			'success-foreground': '#20302a',
			warning: '#e4c766',
			'warning-foreground': '#20302a',
			border: '#3a4e45',
			input: '#3a4e45',
			ring: '#e4c766'
		}
	},
	'6': {
		key: '6',
		name: 'Golden section',
		area: 'Proportion & classical geometry',
		motif: 'golden',
		font: SERIF,
		tokens: {
			background: '#f5f1e8',
			foreground: '#2a2620',
			card: '#fbf8f0',
			'card-foreground': '#2a2620',
			popover: '#fbf8f0',
			'popover-foreground': '#2a2620',
			primary: '#9a7b3f',
			'primary-foreground': '#fbf8f0',
			secondary: '#ebe4d2',
			'secondary-foreground': '#2a2620',
			muted: '#ebe4d2',
			'muted-foreground': '#726a5a',
			accent: '#e6dcc2',
			'accent-foreground': '#2a2620',
			destructive: '#a6482e',
			'destructive-foreground': '#fbf8f0',
			success: '#6e7a3f',
			'success-foreground': '#fbf8f0',
			warning: '#b8862f',
			'warning-foreground': '#2a2620',
			border: '#dfd4be',
			input: '#dfd4be',
			ring: '#9a7b3f'
		}
	},
	'8': {
		key: '8',
		name: 'Modular string art',
		area: 'Modular arithmetic',
		motif: 'cardioid',
		font: SERIF,
		tokens: {
			background: '#141826',
			foreground: '#e8eaf2',
			card: '#1c2133',
			'card-foreground': '#e8eaf2',
			popover: '#1c2133',
			'popover-foreground': '#e8eaf2',
			primary: '#6c8fe0',
			'primary-foreground': '#0f1220',
			secondary: '#232a40',
			'secondary-foreground': '#e8eaf2',
			muted: '#232a40',
			'muted-foreground': '#9aa3c0',
			accent: '#2a3350',
			'accent-foreground': '#e8eaf2',
			destructive: '#e6857f',
			'destructive-foreground': '#141826',
			success: '#7fc0a0',
			'success-foreground': '#141826',
			warning: '#e0b36c',
			'warning-foreground': '#141826',
			border: '#2e3654',
			input: '#2e3654',
			ring: '#6c8fe0'
		}
	}
};

/**
 * Build an inline `style` string for a design wrapper: every token emitted under
 * both `--<name>` (used by Tailwind utilities via `@theme inline`) and
 * `--color-<name>` (used by hand-written rules), plus the font family.
 */
export function designStyle(design: Design): string {
	const vars = Object.entries(design.tokens)
		.map(([k, v]) => `--${k}:${v};--color-${k}:${v}`)
		.join(';');
	return `${vars};font-family:${design.font}`;
}
