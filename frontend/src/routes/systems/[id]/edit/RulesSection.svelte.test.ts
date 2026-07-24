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
	side_conditions: ['not occurs(x, p)'],
	matching: 'structural',
	subproof: null,
	allow_extra_antecedents: false
};

function renderSection(over: Partial<Rule> = {}) {
	const onChanged = vi.fn();
	render(RulesSection, { systemId: 'sys1', rules: [{ ...rule, ...over }], onChanged });
	return { onChanged };
}

describe('RulesSection allow_extra_antecedents', () => {
	it('pre-fills the toggle and sends the flipped value', async () => {
		renderSection({ allow_extra_antecedents: true });
		await userEvent.click(screen.getByRole('button', { name: 'Edit' }));

		// The stored value drives the toggle's label.
		const toggle = screen.getByRole('button', { name: 'Enabled' });
		await userEvent.click(toggle);
		await userEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

		const [, , payload] = vi.mocked(api.parts.rules.update).mock.calls[0];
		expect(payload).toMatchObject({ allow_extra_antecedents: false });
	});

	it('is hidden and forced off for a discharge rule', async () => {
		// A discharge rule carries no antecedents or side-conditions either — the API
		// rejects those pairings too, so the fixture must be a state the API accepts.
		renderSection({
			subproof: { derive: 'q', assume: 'p', fresh: null },
			antecedents: [],
			side_conditions: []
		});
		await userEvent.click(screen.getByRole('button', { name: 'Edit' }));

		// The discharge check cites one subproof opener, so the option is not offered.
		expect(screen.queryByText('Allow extra antecedents')).not.toBeInTheDocument();

		await userEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
		const [, , payload] = vi.mocked(api.parts.rules.update).mock.calls[0];
		expect(payload.allow_extra_antecedents).toBe(false);
	});
});

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

describe('RulesSection matching kind', () => {
	it('defaults a new rule to structural and can switch it to string rewriting', async () => {
		renderSection();
		await userEvent.click(screen.getByRole('button', { name: 'Add rule' }));

		// Minimal required fields so the save can fire.
		await userEvent.type(screen.getByPlaceholderText('e.g. MP'), 'R2');
		await userEvent.type(screen.getByPlaceholderText('e.g. modus ponens'), 'double');
		await userEvent.type(screen.getByPlaceholderText('e.g. q'), 'Mxx');

		await userEvent.click(screen.getByRole('button', { name: 'String rewriting' }));
		await userEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

		expect(vi.mocked(api.parts.rules.create)).toHaveBeenCalledWith(
			'sys1',
			expect.objectContaining({ matching: 'string' })
		);
	});
});
