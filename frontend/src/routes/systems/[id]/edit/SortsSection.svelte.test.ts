import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import SortsSection from './SortsSection.svelte';
import { api } from '$lib/api';
import { toastError, toastSuccess } from '$lib/toast';

// The section talks to the API and the toast helpers; mock both and assert on
// the calls rather than the network / DOM toasts.
vi.mock('$lib/api', () => ({
	api: { parts: { sorts: { create: vi.fn(), update: vi.fn(), remove: vi.fn(), reorder: vi.fn() } } },
	ApiError: class ApiError extends Error {
		status: number;
		detail: unknown;
		constructor(status: number, detail: unknown, message?: string) {
			super(message);
			this.status = status;
			this.detail = detail;
		}
	}
}));
vi.mock('$lib/toast', () => ({ toastSuccess: vi.fn(), toastError: vi.fn() }));

const sorts = api.parts.sorts as unknown as Record<string, ReturnType<typeof vi.fn>>;

// The sheet is a modal (bits-ui): while open it sets `pointer-events: none` on
// the background, which trips user-event's pointer check. Disable that check,
// and reset the body style between tests so a prior sheet can't block the next.
const user = userEvent.setup({ pointerEventsCheck: 0 });

beforeEach(() => {
	sorts.create.mockResolvedValue({ id: 's1', name: 'term' });
	sorts.update.mockResolvedValue({ id: 's1', name: 'term' });
});
afterEach(() => {
	vi.clearAllMocks();
	document.body.style.pointerEvents = '';
});

async function openAddSheet() {
	await user.click(screen.getByRole('button', { name: 'Add sort' }));
	// The sheet content is portalled; wait for it to mount.
	return screen.findByRole('button', { name: /Save changes/ });
}

describe('SortsSection save flow', () => {
	it('gates Save on a non-empty name (canSave)', async () => {
		render(SortsSection, { systemId: 'sys-1', sorts: [], onChanged: vi.fn() });
		const save = await openAddSheet();
		expect(save).toBeDisabled(); // empty name

		await user.type(screen.getByLabelText('Name'), 'term');
		expect(save).toBeEnabled();
	});

	it('creates a new sort, toasts success, and closes the sheet', async () => {
		const onChanged = vi.fn();
		render(SortsSection, { systemId: 'sys-1', sorts: [], onChanged });
		const save = await openAddSheet();

		await user.type(screen.getByLabelText('Name'), 'term');
		await user.click(save);

		expect(sorts.create).toHaveBeenCalledWith('sys-1', { name: 'term' });
		expect(sorts.update).not.toHaveBeenCalled();
		expect(toastSuccess).toHaveBeenCalledWith('Sort added.');
		expect(onChanged).toHaveBeenCalled();
		// Closed on success: the Save button is gone.
		await waitFor(() =>
			expect(screen.queryByRole('button', { name: /Save changes/ })).not.toBeInTheDocument()
		);
	});

	it('updates (not creates) when editing an existing sort', async () => {
		render(SortsSection, {
			systemId: 'sys-1',
			sorts: [{ id: 's1', name: 'term' }],
			onChanged: vi.fn()
		});
		// Each row has an Edit button (from PartSection).
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		const save = await screen.findByRole('button', { name: /Save changes/ });

		await user.click(save); // name pre-filled, so save is enabled
		expect(sorts.update).toHaveBeenCalledWith('sys-1', 's1', { name: 'term' });
		expect(sorts.create).not.toHaveBeenCalled();
	});

	it('keeps the sheet open and toasts on failure', async () => {
		sorts.create.mockRejectedValueOnce(new Error('boom'));
		const onChanged = vi.fn();
		render(SortsSection, { systemId: 'sys-1', sorts: [], onChanged });
		const save = await openAddSheet();

		await user.type(screen.getByLabelText('Name'), 'term');
		await user.click(save);

		expect(toastError).toHaveBeenCalled();
		expect(onChanged).not.toHaveBeenCalled();
		// Still open: the Save button is present.
		expect(screen.getByRole('button', { name: /Save changes/ })).toBeInTheDocument();
	});
});
