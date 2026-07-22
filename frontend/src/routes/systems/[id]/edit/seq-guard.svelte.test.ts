import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';
import EditPage from './+page.svelte';
import { page } from '$lib/testing/page-mock.svelte';
import { auth } from '$lib/auth.svelte';
import { api } from '$lib/api';

// Drive the route param through a reactive `$app/state` stand-in so changing
// `page.params.id` re-runs the page's load effect (see page-mock.svelte.ts).
vi.mock('$app/state', async () => await import('$lib/testing/page-mock.svelte'));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/api', () => ({
	api: { me: vi.fn(), systems: { get: vi.fn(), validate: vi.fn() } },
	ApiError: class ApiError extends Error {}
}));
vi.mock('$lib/toast', () => ({ toastSuccess: vi.fn(), toastError: vi.fn() }));

const apiMock = api as unknown as {
	me: ReturnType<typeof vi.fn>;
	systems: { get: ReturnType<typeof vi.fn>; validate: ReturnType<typeof vi.fn> };
};

const USER = {
	id: 'u1',
	email: 'a@b.c',
	is_active: true,
	is_superuser: false,
	is_verified: true,
	display_name: 'Ada'
};

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((r) => (resolve = r));
	return { promise, resolve };
}

function makeSystem(id: string, name: string) {
	return {
		id,
		name,
		slug: name.toLowerCase(),
		description: null,
		inherits_from_id: null,
		published_at: null,
		created_at: '2026-01-01T00:00:00Z',
		updated_at: '2026-01-01T00:00:00Z',
		owner: { id: 'u1', display_name: 'Ada' },
		brackets: [],
		sorts: [],
		productions: [],
		lines: [],
		definitions: [],
		axioms: [],
		rules: []
	};
}

beforeEach(async () => {
	apiMock.me.mockResolvedValue(USER);
	await auth.refresh(); // sign in so the owner can edit
	apiMock.systems.validate.mockResolvedValue({
		success: true,
		errors: [],
		system_name: 'X',
		line_type_count: 0,
		inference_rule_count: 0
	});
	page.params.id = '';
});
afterEach(() => vi.clearAllMocks());

describe('edit page load sequencing', () => {
	it('a stale load resolving last does not clobber the newer system', async () => {
		const getA = deferred<ReturnType<typeof makeSystem>>();
		const getB = deferred<ReturnType<typeof makeSystem>>();
		apiMock.systems.get.mockImplementation((id: string) =>
			id === 'A' ? getA.promise : getB.promise
		);

		// Mount on system A → load('A') starts and awaits its fetch.
		page.params.id = 'A';
		render(EditPage);
		await tick();

		// Navigate to B before A resolves → load('B') starts (loadSeq now leads).
		page.params.id = 'B';
		await tick();

		// The newer load resolves first; B is shown.
		getB.resolve(makeSystem('B', 'Beta'));
		await waitFor(() => expect(screen.getByText('Beta')).toBeInTheDocument());

		// The stale load for A resolves last — its guard must drop it.
		getA.resolve(makeSystem('A', 'Alpha'));
		await tick();
		await tick();

		expect(screen.queryByText('Alpha')).not.toBeInTheDocument();
		expect(screen.getByText('Beta')).toBeInTheDocument();
	});
});
