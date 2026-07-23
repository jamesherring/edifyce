import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { api } from '$lib/api';
import type { Definition } from '$lib/api';
import DefinitionsSection from './DefinitionsSection.svelte';

// The section only side-effects through the api client and toasts; mock both and
// assert on the payload the save sends.
vi.mock('$lib/api', () => ({
	api: {
		parts: {
			definitions: {
				create: vi.fn().mockResolvedValue({}),
				update: vi.fn().mockResolvedValue({}),
				remove: vi.fn().mockResolvedValue(undefined),
				reorder: vi.fn().mockResolvedValue(undefined)
			}
		}
	},
	ApiError: class ApiError extends Error {}
}));
vi.mock('$lib/toast', () => ({ toastSuccess: vi.fn(), toastError: vi.fn() }));

function defn(over: Partial<Definition> = {}): Definition {
	return {
		id: 'd1',
		sort: 'formula',
		name: 'subset',
		higher: 'x sub y',
		lower: 'all z (z in x -> z in y)',
		provisos: ['disjoint(x, y)'],
		condition: 'disjoint(x, y)',
		bindings: [
			{ var: 'x', sort: 'variable' },
			{ var: 'y', sort: 'variable' }
		],
		...over
	};
}

function renderSection(definitions: Definition[]) {
	const onChanged = vi.fn();
	render(DefinitionsSection, { systemId: 'sys1', definitions, sortNames: ['formula'], onChanged });
	return { onChanged };
}

describe('DefinitionsSection provisos', () => {
	it('pre-fills the provisos editor from a definition’s provisos', async () => {
		renderSection([defn()]);
		await userEvent.click(screen.getByRole('button', { name: 'Edit' }));
		expect(screen.getByDisplayValue('disjoint(x, y)')).toBeInTheDocument();
	});

	it('sends edited provisos (trimmed, blank-filtered) and no condition', async () => {
		renderSection([defn()]);
		await userEvent.click(screen.getByRole('button', { name: 'Edit' }));

		// Add a second proviso and a blank one; the blank must be dropped.
		await userEvent.click(screen.getByRole('button', { name: 'Add proviso' }));
		await userEvent.click(screen.getByRole('button', { name: 'Add proviso' }));
		const inputs = screen.getAllByPlaceholderText('e.g. disjoint(x, y)');
		await userEvent.type(inputs[1], '  not occurs(x, y)  ');
		// inputs[2] left blank

		await userEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

		const [, , payload] = vi.mocked(api.parts.definitions.update).mock.calls[0];
		expect(payload).toMatchObject({ provisos: ['disjoint(x, y)', 'not occurs(x, y)'] });
		// The deprecated `condition` field is no longer sent from the editor.
		expect(payload).not.toHaveProperty('condition');
	});
});

describe('DefinitionsSection layering', () => {
	it('inserts an earlier definition’s notation into the expansion', async () => {
		const earlier = defn({ id: 'd0', name: 'member', higher: 'x in y', lower: '…', provisos: [] });
		const later = defn({ id: 'd1', name: 'subset', higher: 'x sub y', lower: '', provisos: [] });
		renderSection([earlier, later]);

		// Edit the *second* definition — only the earlier one is offered to build on.
		// Target the picker by its placeholder text (the native Sort <select> also
		// has the `combobox` role, and bits-ui doesn't expose the placeholder as the
		// trigger's accessible name).
		await userEvent.click(screen.getAllByRole('button', { name: 'Edit' })[1]);
		// The picker trigger is the <button> combobox (the Sort <select> shares the
		// role); click it to open, then choose the earlier definition's notation.
		const picker = screen
			.getAllByRole('combobox')
			.find((el) => el.tagName === 'BUTTON');
		await userEvent.click(picker!);
		// Target the picker's own option by its command-item slot — the notation
		// also shows in the definition list row, and the BindingsEditor's <select>s
		// contribute their own role="option" elements.
		const option = await waitFor(() => {
			const el = document.querySelector<HTMLElement>('[data-slot="command-item"]');
			if (!el) throw new Error('option not yet rendered');
			return el;
		});
		await userEvent.click(option);

		// Its notation is appended to the (empty) expansion input.
		expect(screen.getByDisplayValue('x in y')).toBeInTheDocument();
	});

	it('offers nothing to build on for the first definition', async () => {
		renderSection([defn({ id: 'd0', lower: 'first' })]);
		await userEvent.click(screen.getByRole('button', { name: 'Edit' }));
		// The layering picker only renders when an earlier definition exists.
		expect(screen.queryByText('Build on an earlier definition…')).not.toBeInTheDocument();
	});
});
