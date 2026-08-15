import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import Page from './+page.svelte';
import { auth } from '$lib/auth.svelte';
import { api } from '$lib/api';

// This file mounts the page with auth *unresolved* (auth.ready === false), so it
// observes the real `false → true` transition when auth resolves — the moment at
// which a regression could fetch the wrong list, or fetch twice. It lives in its
// own file because auth.ready is monotonic (never resets to false) and Vitest
// isolates the module singleton per file.
vi.mock('$app/navigation', () => ({ goto: vi.fn(), beforeNavigate: vi.fn() }));
vi.mock('$lib/api', () => ({
	api: {
		me: vi.fn(),
		logout: vi.fn().mockResolvedValue(undefined),
		systems: { list: vi.fn(), listPublic: vi.fn() }
	},
	ApiError: class ApiError extends Error {}
}));

const apiMock = api as unknown as {
	me: ReturnType<typeof vi.fn>;
	systems: { list: ReturnType<typeof vi.fn>; listPublic: ReturnType<typeof vi.fn> };
};

beforeEach(() => {
	const emptyPage = { items: [], total: 0, limit: 10, offset: 0 };
	apiMock.systems.list.mockResolvedValue(emptyPage);
	apiMock.systems.listPublic.mockResolvedValue(emptyPage);
});
afterEach(() => vi.clearAllMocks());

describe('systems list initial fetch', () => {
	it('waits for auth, then fetches the right list exactly once', async () => {
		// Mounted with auth.ready === false. Which list this visitor should see
		// depends on who they are, so nothing is requested yet — fetching the
		// public list here would be a wasted request and a flash of the wrong rows.
		render(Page);
		await tick();
		await Promise.resolve();
		expect(apiMock.systems.listPublic).not.toHaveBeenCalled();
		expect(apiMock.systems.list).not.toHaveBeenCalled();

		// Resolve auth: ready flips false → true, with a signed-in user.
		apiMock.me.mockResolvedValue({
			id: 'u1',
			email: 'a@b.c',
			is_active: true,
			is_superuser: false,
			is_verified: true,
			display_name: 'Ada'
		});
		await auth.refresh();

		// Their own systems are the default, fetched once — and the public list is
		// never fetched on the way there.
		await waitFor(() => expect(apiMock.systems.list).toHaveBeenCalledTimes(1));
		expect(apiMock.systems.listPublic).not.toHaveBeenCalled();

		// Settling must not trigger a second fetch.
		await tick();
		await Promise.resolve();
		expect(apiMock.systems.list).toHaveBeenCalledTimes(1);
	});
});
