import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import Page from './+page.svelte';
import { auth } from '$lib/auth.svelte';
import { api } from '$lib/api';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/api', () => ({
	api: {
		me: vi.fn(),
		logout: vi.fn().mockResolvedValue(undefined),
		systems: { list: vi.fn(), listPublic: vi.fn() }
	},
	ApiError: class ApiError extends Error {}
}));

const user = userEvent.setup();
const apiMock = api as unknown as {
	me: ReturnType<typeof vi.fn>;
	logout: ReturnType<typeof vi.fn>;
	systems: { list: ReturnType<typeof vi.fn>; listPublic: ReturnType<typeof vi.fn> };
};

const USER = {
	id: 'u1',
	email: 'a@b.c',
	is_active: true,
	is_superuser: false,
	is_verified: true,
	display_name: 'Ada'
};

beforeEach(async () => {
	apiMock.systems.list.mockResolvedValue([]);
	apiMock.systems.listPublic.mockResolvedValue([]);
	apiMock.logout.mockResolvedValue(undefined);
	// Sign in through the real auth store (ready becomes true).
	apiMock.me.mockResolvedValue(USER);
	await auth.refresh();
});
afterEach(async () => {
	await auth.logout(); // reset the singleton between tests
	vi.clearAllMocks();
});

describe('systems list', () => {
	it('falls back to the public view when the user logs out of "My systems"', async () => {
		render(Page);
		// Owner is signed in → the view toggle is present. Switch to "My systems".
		await user.click(await screen.findByRole('button', { name: 'My systems' }));
		await waitFor(() => expect(apiMock.systems.list).toHaveBeenCalled());

		// Isolate the post-logout fetch from the mount fetch.
		apiMock.systems.listPublic.mockClear();

		// Log out: the store's user goes null.
		await auth.logout();

		// The reset effect flips the view back to public → fetches the public list…
		await waitFor(() => expect(apiMock.systems.listPublic).toHaveBeenCalled());
		// …and the owner-only toggle is gone.
		expect(screen.queryByRole('button', { name: 'My systems' })).not.toBeInTheDocument();
	});

	it('does not re-fetch the public list a second time when auth resolves', async () => {
		// The public view must not depend on auth.ready (P1: no double fetch).
		render(Page);
		await waitFor(() => expect(apiMock.systems.listPublic).toHaveBeenCalledTimes(1));
		// Nudge auth (a no-op refresh); the public view must not re-fetch.
		await auth.refresh();
		await Promise.resolve();
		expect(apiMock.systems.listPublic).toHaveBeenCalledTimes(1);
	});
});
