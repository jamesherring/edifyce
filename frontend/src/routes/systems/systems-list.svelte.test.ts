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
	const emptyPage = { items: [], total: 0, limit: 10, offset: 0 };
	apiMock.systems.list.mockResolvedValue(emptyPage);
	apiMock.systems.listPublic.mockResolvedValue(emptyPage);
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

	it('requests pages from the server and re-fetches on navigation', async () => {
		// A full page of 10 rows out of 25 total → the server owns the paging, and
		// the pagination controls appear because total exceeds the page size.
		const rows = Array.from({ length: 10 }, (_, i) => ({
			id: `s${i}`,
			name: `System ${i}`,
			slug: `system-${i}`,
			description: null,
			inherits_from_id: null,
			published_at: '2020-01-01T00:00:00Z',
			created_at: '2020-01-01T00:00:00Z',
			updated_at: '2020-01-01T00:00:00Z',
			owner: { id: 'u1', display_name: 'Ada' }
		}));
		apiMock.systems.listPublic.mockResolvedValue({ items: rows, total: 25, limit: 10, offset: 0 });

		render(Page);
		// The first request asks for page one (offset 0) at the configured size.
		await waitFor(() =>
			expect(apiMock.systems.listPublic).toHaveBeenLastCalledWith(
				expect.objectContaining({ limit: 10, offset: 0 })
			)
		);

		// Navigating forward re-queries the server at the next offset — proof the
		// paging is server-side, not a client-side slice of one big response.
		await user.click(await screen.findByRole('button', { name: 'Next page' }));
		await waitFor(() =>
			expect(apiMock.systems.listPublic).toHaveBeenLastCalledWith(
				expect.objectContaining({ offset: 10 })
			)
		);
	});
});
