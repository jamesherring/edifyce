import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import Page from './+page.svelte';
import { auth } from '$lib/auth.svelte';
import { api } from '$lib/api';

// This file mounts the page with auth *unresolved* (auth.ready === false), so it
// observes the real `false → true` transition when auth resolves — the moment a
// regression that made the public view depend on auth.ready would double-fetch.
// It lives in its own file because auth.ready is monotonic (never resets to
// false) and Vitest isolates the module singleton per file.
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
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
	it('does not re-fetch the public list when auth resolves (false → true)', async () => {
		// Mounted with auth.ready === false (no refresh has run yet in this module).
		render(Page);
		await waitFor(() => expect(apiMock.systems.listPublic).toHaveBeenCalledTimes(1));

		// Resolve auth: ready flips false → true. The public view must not depend
		// on auth.ready, so this must NOT trigger a second fetch.
		apiMock.me.mockResolvedValue({
			id: 'u1',
			email: 'a@b.c',
			is_active: true,
			is_superuser: false,
			is_verified: true,
			display_name: 'Ada'
		});
		await auth.refresh();
		await tick();
		await Promise.resolve();

		expect(apiMock.systems.listPublic).toHaveBeenCalledTimes(1);
	});
});
