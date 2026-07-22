import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { api } from '$lib/api';
import type { Rule } from '$lib/api';
import RulesSection from './RulesSection.svelte';

// The section only side-effects through the api client and toasts; mock both and
// assert on the payload the save sends.
vi.mock('$lib/api', () => ({
	api: {
		parts: {
			rules: {
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

const rule: Rule = {
	id: 'r1',
	label: 'AllI',
	name: 'forall-intro',
	deduction: '∀x p',
	antecedents: ['p'],
	bindings: [
		{ var: 'x', sort: 'variable' },
		{ var: 'p', sort: 'formula' }
	],
	side_conditions: ['not occurs(x, p)']
};

function renderSection() {
	const onChanged = vi.fn();
	render(RulesSection, { systemId: 'sys1', rules: [rule], onChanged });
	return { onChanged };
}

describe('RulesSection provisos', () => {
	it('pre-fills the provisos editor from a rule’s side_conditions', async () => {
		renderSection();
		await userEvent.click(screen.getByRole('button', { name: 'Edit' }));
		expect(screen.getByDisplayValue('not occurs(x, p)')).toBeInTheDocument();
	});

	it('sends edited provisos in the update payload, trimmed and blank-filtered', async () => {
		renderSection();
		await userEvent.click(screen.getByRole('button', { name: 'Edit' }));

		// Add a second proviso and a blank one; the blank must be dropped.
		await userEvent.click(screen.getByRole('button', { name: 'Add proviso' }));
		await userEvent.click(screen.getByRole('button', { name: 'Add proviso' }));
		const inputs = screen.getAllByPlaceholderText('e.g. not occurs(x, p)');
		await userEvent.type(inputs[1], '  equal(x, p)  ');
		// inputs[2] left blank

		await userEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

		expect(vi.mocked(api.parts.rules.update)).toHaveBeenCalledWith(
			'sys1',
			'r1',
			expect.objectContaining({ side_conditions: ['not occurs(x, p)', 'equal(x, p)'] })
		);
	});
});
