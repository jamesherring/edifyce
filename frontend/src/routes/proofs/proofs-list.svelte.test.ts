import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import Page from './+page.svelte';
import { auth } from '$lib/auth.svelte';
import { api } from '$lib/api';
import type { ProofSummary } from '$lib/api';

vi.mock('$app/navigation', () => ({ goto: vi.fn(), beforeNavigate: vi.fn() }));
vi.mock('$lib/api', () => ({
	api: {
		me: vi.fn(),
		logout: vi.fn().mockResolvedValue(undefined),
		proofs: { list: vi.fn(), listPublic: vi.fn() }
	},
	ApiError: class ApiError extends Error {}
}));

const apiMock = api as unknown as {
	me: ReturnType<typeof vi.fn>;
	logout: ReturnType<typeof vi.fn>;
	proofs: { list: ReturnType<typeof vi.fn>; listPublic: ReturnType<typeof vi.fn> };
};

function summary(over: Partial<ProofSummary> = {}): ProofSummary {
	return {
		id: 'p1',
		name: 'sqrt2irr',
		slug: 'sqrt2irr',
		title: null,
		description: null,
		formal_system_id: 'sys1',
		folder_id: null,
		valid: null,
		published_at: '2020-01-01T00:00:00Z',
		created_at: '2020-01-01T00:00:00Z',
		updated_at: '2020-01-01T00:00:00Z',
		owner: null,
		...over
	};
}

function serve(rows: ProofSummary[]) {
	const page = { items: rows, total: rows.length, limit: 10, offset: 0 };
	apiMock.proofs.list.mockResolvedValue(page);
	apiMock.proofs.listPublic.mockResolvedValue(page);
}

beforeEach(async () => {
	serve([]);
	apiMock.logout.mockResolvedValue(undefined);
	apiMock.me.mockRejectedValue(new Error('anonymous'));
	await auth.refresh();
});
afterEach(async () => {
	await auth.logout();
	vi.clearAllMocks();
});

describe('the proof list', () => {
	it('shows an imported proof by its title, since its name is a bare label', async () => {
		// The corpus case, and the reason `title` is on `ProofSummary` at all:
		// `sqrt2irr` says nothing on its own, and an import leaves `description`
		// empty deliberately — a corpus comment runs to paragraphs.
		serve([summary({ title: 'The square root of 2 is irrational.' })]);
		render(Page);

		await waitFor(() =>
			expect(screen.getByText('The square root of 2 is irrational.')).toBeInTheDocument()
		);
		expect(screen.getByText('sqrt2irr')).toBeInTheDocument();
	});

	it('falls back to the description for a proof that has no title', async () => {
		// The hand-authored case, unchanged: `name` is already the human one and the
		// description is what the author wrote about it.
		serve([summary({ name: 'Assoc', description: 'Conjunction is associative.' })]);
		render(Page);

		await waitFor(() =>
			expect(screen.getByText('Conjunction is associative.')).toBeInTheDocument()
		);
	});

	it('shows a dash when a proof says neither', async () => {
		// The author is named so that the only dash on the page is the description's.
		serve([summary({ owner: { id: 'u1', display_name: 'Ada' } })]);
		render(Page);

		await waitFor(() => expect(screen.getByText('sqrt2irr')).toBeInTheDocument());
		expect(screen.getByText('—')).toBeInTheDocument();
	});
});
