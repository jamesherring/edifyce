import { afterEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import SymbolPalette from './SymbolPalette.svelte';
import type { SymbolEntry } from '$lib/symbols';

const user = userEvent.setup();

const SYSTEM: SymbolEntry[] = [
	{ char: '∈', name: 'is a member of' },
	{ char: '⊆', name: 'is a subset of' }
];

let root: HTMLDivElement | null = null;

/** Mount a palette over a container holding two marked fields, mimicking a form. */
function setup(symbols: SymbolEntry[] = SYSTEM) {
	root = document.createElement('div');
	root.innerHTML =
		'<input data-symbol-field id="first" /><input data-symbol-field id="second" />';
	document.body.appendChild(root);
	render(SymbolPalette, { root, symbols });
	return {
		first: root.querySelector('#first') as HTMLInputElement,
		second: root.querySelector('#second') as HTMLInputElement
	};
}

afterEach(() => {
	root?.remove();
	root = null;
});

describe('SymbolPalette', () => {
	it('leads with the system’s own symbols', () => {
		setup();
		expect(screen.getByRole('button', { name: 'Insert is a member of' })).toBeInTheDocument();
		// A catalogue-only symbol stays behind "More symbols" until asked for.
		expect(screen.queryByRole('button', { name: 'Insert capital gamma' })).toBeNull();
	});

	it('falls back to a starter row for a system with no notation yet', () => {
		setup([]);
		expect(screen.getByRole('button', { name: 'Insert not' })).toBeInTheDocument();
	});

	it('inserts at the caret of the last-focused field', async () => {
		const { first, second } = setup();
		second.focus();
		second.value = 'xy';
		second.setSelectionRange(1, 1);

		await user.click(screen.getByRole('button', { name: 'Insert is a member of' }));

		expect(second.value).toBe('x∈y');
		expect(second.selectionStart).toBe(2);
		expect(first.value).toBe('');
	});

	it('replaces the selection, as typing would', async () => {
		const { first } = setup();
		first.focus();
		first.value = 'a?b';
		first.setSelectionRange(1, 2);

		await user.click(screen.getByRole('button', { name: 'Insert is a subset of' }));

		expect(first.value).toBe('a⊆b');
	});

	it('inserts into the first field when nothing has been focused yet', async () => {
		const { first } = setup();
		await user.click(screen.getByRole('button', { name: 'Insert is a member of' }));
		expect(first.value).toBe('∈');
	});

	it('drops the insert when the focused field has been removed, rather than retargeting', async () => {
		const { first, second } = setup();
		second.focus();
		second.remove();

		await user.click(screen.getByRole('button', { name: 'Insert is a member of' }));

		// Writing into `first` here would mutate a field the user never touched.
		expect(first.value).toBe('');
	});

	it('reveals the whole catalogue, filtered by a search', async () => {
		setup();
		await user.click(screen.getByRole('button', { name: 'More symbols' }));
		expect(screen.getByRole('button', { name: 'Insert capital gamma' })).toBeInTheDocument();

		await user.type(screen.getByRole('textbox', { name: 'Search symbols' }), 'subset');
		expect(screen.getByRole('button', { name: 'Insert is a proper subset of' })).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Insert capital gamma' })).toBeNull();
	});

	it('keeps the whole catalogue to a single tab stop', async () => {
		setup();
		await user.click(screen.getByRole('button', { name: 'More symbols' }));
		const catalogue = screen.getByRole('toolbar', { name: 'Symbol catalogue' });
		const keys = [...catalogue.querySelectorAll('button')];
		// Otherwise reaching the editor below means tabbing past every symbol.
		expect(keys.length).toBeGreaterThan(100);
		expect(keys.filter((b) => b.tabIndex === 0)).toHaveLength(1);
	});

	it('keeps a tab stop in the catalogue when a search narrows it', async () => {
		setup();
		await user.click(screen.getByRole('button', { name: 'More symbols' }));
		const catalogue = screen.getByRole('toolbar', { name: 'Symbol catalogue' });
		catalogue.querySelector('button')!.focus();
		await user.keyboard('{End}');

		await user.type(screen.getByRole('textbox', { name: 'Search symbols' }), 'subset');

		const keys = [...catalogue.querySelectorAll('button')];
		expect(keys.filter((b) => b.tabIndex === 0)).toHaveLength(1);
	});

	it('is one tab stop, with the arrow keys moving between symbols', async () => {
		setup();
		const member = screen.getByRole('button', { name: 'Insert is a member of' });
		const subset = screen.getByRole('button', { name: 'Insert is a subset of' });
		expect(member.tabIndex).toBe(0);
		expect(subset.tabIndex).toBe(-1);

		member.focus();
		await user.keyboard('{ArrowRight}');
		expect(document.activeElement).toBe(subset);
		expect(subset.tabIndex).toBe(0);
		expect(member.tabIndex).toBe(-1);
	});
});
