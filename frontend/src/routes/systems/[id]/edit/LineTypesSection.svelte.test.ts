import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import LineTypesSection from './LineTypesSection.svelte';

vi.mock('$lib/api', () => ({
	api: {
		parts: { lineTypes: { create: vi.fn(), update: vi.fn(), remove: vi.fn(), reorder: vi.fn() } }
	},
	ApiError: class ApiError extends Error {}
}));
vi.mock('$lib/toast', () => ({ toastSuccess: vi.fn(), toastError: vi.fn() }));

const user = userEvent.setup({ pointerEventsCheck: 0 });
afterEach(() => {
	vi.clearAllMocks();
	document.body.style.pointerEvents = '';
});

function line(logicalSort: string | null) {
	return { id: 'l1', name: 'statement', shape: '<formula>', logical_sort: logicalSort, scope: null, parts: [] };
}

// The P1 fix: the logical sort is optional (empty = none), but a non-empty value
// must name a real sort — the stored one may have been deleted since.
describe('LineTypesSection logical-sort validation', () => {
	it('disables Save when the stored logical sort is no longer known', async () => {
		render(LineTypesSection, {
			systemId: 'sys-1',
			lines: [line('ghost')], // 'ghost' was deleted
			sortNames: ['term', 'formula'],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: 'Edit' }));
		const save = await screen.findByRole('button', { name: /Save Changes/ });

		// Name + shape are filled, so only the stale logical sort blocks Save.
		expect(save).toBeDisabled();

		// "— none —" (empty) is valid, since the logical sort is optional.
		await user.selectOptions(screen.getByLabelText(/Logical sort/), '');
		expect(save).toBeEnabled();
	});

	it('enables Save when there is no logical sort at all', async () => {
		render(LineTypesSection, {
			systemId: 'sys-1',
			lines: [line(null)],
			sortNames: ['term', 'formula'],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: 'Edit' }));
		const save = await screen.findByRole('button', { name: /Save Changes/ });
		expect(save).toBeEnabled();
	});
});
