import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import LineTypesSection from './LineTypesSection.svelte';
import type { LineType } from '$lib/api';

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

function line(logicalSort: string | null, over: Partial<LineType> = {}): LineType {
	return {
		id: 'l1',
		name: 'statement',
		shape: '<formula>',
		logical_sort: logicalSort,
		scope: null,
		behaviour: 'logical',
		parts: [],
		...over
	};
}

// The P1 fix: the logical sort is optional (empty = none), but a non-empty value
// must name a real sort — the stored one may have been deleted since.
describe('LineTypesSection logical-sort validation', () => {
	it('disables Save when the stored logical sort is no longer known', async () => {
		render(LineTypesSection, {
			systemId: 'sys-1',
			lines: [line('ghost')], // 'ghost' was deleted
			sortNames: ['term', 'formula'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		const save = await screen.findByRole('button', { name: /Save changes/ });

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
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		const save = await screen.findByRole('button', { name: /Save changes/ });
		expect(save).toBeEnabled();
	});
});

describe('LineTypesSection commentary', () => {
	function renderWith(over: Partial<LineType> = {}) {
		render(LineTypesSection, {
			systemId: 'sys-1',
			lines: [line('formula', over)],
			sortNames: ['term', 'formula'],
			symbols: [],
			onChanged: vi.fn()
		});
	}

	it('pre-fills the toggle and hides the fields a comment cannot carry', async () => {
		renderWith({ behaviour: 'comment', logical_sort: null });
		await user.click(screen.getByRole('button', { name: /^Edit / }));

		expect(screen.getByRole('button', { name: 'Enabled' })).toBeInTheDocument();
		// A comment bears no formula and opens no scope, so neither is offered.
		expect(screen.queryByLabelText(/Logical sort/)).not.toBeInTheDocument();
		expect(screen.queryByLabelText(/Opens scope/)).not.toBeInTheDocument();
	});

	it('clears the sort and scope when a logical line is turned into commentary', async () => {
		// The API rejects both pairings, so the save must send nulls rather than
		// carry the now-hidden values through.
		renderWith({ scope: 'assumption' });
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		await user.click(screen.getByRole('button', { name: 'Off' }));
		await user.click(screen.getByRole('button', { name: /Save changes/ }));

		const { api } = await import('$lib/api');
		expect(vi.mocked(api.parts.lineTypes.update)).toHaveBeenCalledWith(
			'sys-1',
			'l1',
			expect.objectContaining({ behaviour: 'comment', logical_sort: null, scope: null })
		);
	});
});
