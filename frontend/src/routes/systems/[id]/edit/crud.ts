import { ApiError } from '$lib/api';
import { toastSuccess, toastError } from '$lib/toast';

/**
 * Run a single part mutation with the shared success/error handling every
 * section needs: toast the outcome and report whether it succeeded, so the
 * caller only decides what to do on success (close the sheet, refresh, …).
 * Pass no `successMessage` to stay quiet on success (e.g. reordering).
 */
export async function runMutation(
	action: () => Promise<unknown>,
	successMessage?: string
): Promise<boolean> {
	try {
		await action();
		if (successMessage) toastSuccess(successMessage);
		return true;
	} catch (err) {
		toastError(err instanceof ApiError ? err.message : String(err));
		return false;
	}
}
