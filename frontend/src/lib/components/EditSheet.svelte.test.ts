import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { createRawSnippet } from 'svelte';
import EditSheet from './EditSheet.svelte';
import type { SymbolEntry } from '$lib/symbols';
import type { NotationGroup } from '$lib/notation';

const user = userEvent.setup();

const SYMBOLS: SymbolEntry[] = [{ char: '∈', name: 'is a member of' }];
const NOTATION: NotationGroup[] = [
	{ title: 'Sorts', entries: [{ form: 'formula', detail: '' }] }
];

const children = createRawSnippet(() => ({
	render: () => '<label for="f">Formula</label><input id="f" data-symbol-field />'
}));

function setup(over: Record<string, unknown> = {}) {
	render(EditSheet, {
		open: true,
		onOpenChange: vi.fn(),
		title: 'Add rule',
		onSave: vi.fn(),
		children,
		...over
	});
}

describe('EditSheet authoring aids', () => {
	it('shows neither aid when the sheet is given neither', () => {
		setup();
		expect(screen.queryByRole('button', { name: 'More symbols' })).toBeNull();
		expect(screen.queryByRole('button', { name: 'Notation reference' })).toBeNull();
	});

	it('shows the notation reference even without a symbol palette', () => {
		setup({ notation: NOTATION });
		expect(screen.getByRole('button', { name: 'Notation reference' })).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'More symbols' })).toBeNull();
	});

	it('keeps only one aid open, so the form is never starved of room', async () => {
		setup({ symbols: SYMBOLS, notation: NOTATION });

		await user.click(screen.getByRole('button', { name: 'More symbols' }));
		expect(screen.getByRole('toolbar', { name: 'Symbol catalogue' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Notation reference' })).toHaveAttribute(
			'aria-expanded',
			'false'
		);

		// Opening the reference must fold the catalogue away, not stack on top of it:
		// on a phone two expanded aids left the fields unreachable.
		await user.click(screen.getByRole('button', { name: 'Notation reference' }));
		expect(screen.queryByRole('toolbar', { name: 'Symbol catalogue' })).toBeNull();
		expect(screen.getByRole('button', { name: 'Notation reference' })).toHaveAttribute(
			'aria-expanded',
			'true'
		);

		// …and back the other way.
		await user.click(screen.getByRole('button', { name: 'More symbols' }));
		expect(screen.getByRole('toolbar', { name: 'Symbol catalogue' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Notation reference' })).toHaveAttribute(
			'aria-expanded',
			'false'
		);
	});
});
