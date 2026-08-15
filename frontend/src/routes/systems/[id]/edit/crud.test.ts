import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '$lib/api';
import { toastError, toastSuccess } from '$lib/toast';
import { runMutation } from './crud';

// Toasts are the only side effect; assert on them rather than on the DOM.
vi.mock('$lib/toast', () => ({
	toastSuccess: vi.fn(),
	toastError: vi.fn()
}));

describe('runMutation', () => {
	it('toasts the success message and returns true when the action resolves', async () => {
		const action = vi.fn().mockResolvedValue(undefined);
		await expect(runMutation(action, 'Saved.')).resolves.toBe(true);
		expect(action).toHaveBeenCalledOnce();
		expect(toastSuccess).toHaveBeenCalledWith('Saved.');
		expect(toastError).not.toHaveBeenCalled();
	});

	it('stays quiet on success when no message is given (e.g. reordering)', async () => {
		await expect(runMutation(vi.fn().mockResolvedValue(undefined))).resolves.toBe(true);
		expect(toastSuccess).not.toHaveBeenCalled();
	});

	it('toasts an ApiError message and returns false when the action rejects', async () => {
		const action = vi.fn().mockRejectedValue(new ApiError(400, 'x', 'Name already taken.'));
		await expect(runMutation(action, 'Saved.')).resolves.toBe(false);
		expect(toastError).toHaveBeenCalledWith('Name already taken.');
		expect(toastSuccess).not.toHaveBeenCalled();
	});

	it('stringifies a non-ApiError failure', async () => {
		const action = vi.fn().mockRejectedValue(new Error('boom'));
		await expect(runMutation(action)).resolves.toBe(false);
		expect(toastError).toHaveBeenCalledWith('Error: boom');
	});
});
