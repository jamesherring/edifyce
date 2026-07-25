import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import ProductionsSection from './ProductionsSection.svelte';

vi.mock('$lib/api', () => ({
	api: {
		parts: { productions: { create: vi.fn(), update: vi.fn(), remove: vi.fn(), reorder: vi.fn() } }
	},
	ApiError: class ApiError extends Error {}
}));
vi.mock('$lib/toast', () => ({ toastSuccess: vi.fn(), toastError: vi.fn() }));

const user = userEvent.setup({ pointerEventsCheck: 0 });
afterEach(() => {
	vi.clearAllMocks();
	document.body.style.pointerEvents = '';
});

function prod(sort: string) {
	return {
		id: 'p1',
		name: 'membership',
		sort,
		kind: 'composite',
		template: 's ∈ t',
		regex: null,
		atom_value: null,
		atom_base: null,
		bindings: []
	};
}

// The P1 fix: a production's stored sort may have been deleted since, leaving the
// <select> blank on a stale value. canSave must validate it against the live
// sort names so an invalid value can't be submitted.
describe('ProductionsSection sort validation', () => {
	it('disables Save when the stored sort is no longer a known sort', async () => {
		render(ProductionsSection, {
			systemId: 'sys-1',
			productions: [prod('ghost')], // 'ghost' was deleted
			sortNames: ['term', 'formula'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		const save = await screen.findByRole('button', { name: /Save changes/ });

		// Name + template are filled from the production, so only the stale sort
		// keeps Save disabled.
		expect(save).toBeDisabled();

		// Picking a real sort clears it.
		await user.selectOptions(screen.getByLabelText('Sort'), 'formula');
		expect(save).toBeEnabled();
	});

	it('enables Save when the stored sort is still valid', async () => {
		render(ProductionsSection, {
			systemId: 'sys-1',
			productions: [prod('formula')],
			sortNames: ['term', 'formula'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		const save = await screen.findByRole('button', { name: /Save changes/ });
		expect(save).toBeEnabled();
	});
});

describe('ProductionsSection atom productions', () => {
	function atomFamily() {
		return {
			id: 'p2',
			name: 'prop',
			sort: 'formula',
			kind: 'atom',
			template: null,
			regex: null,
			atom_value: null,
			atom_base: 'p',
			bindings: []
		};
	}

	it('opens an atom family in Family mode showing its base', async () => {
		render(ProductionsSection, {
			systemId: 'sys-1',
			productions: [atomFamily()],
			sortNames: ['formula'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		await screen.findByRole('button', { name: /Save changes/ });
		// fill() picked the atom_base discriminator, so the value input holds the base.
		expect(screen.getByDisplayValue('p')).toBeTruthy();
	});
});
