import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import Page from './+page.svelte';
import { auth } from '$lib/auth.svelte';
import { api } from '$lib/api';
import type { ProofDetail } from '$lib/api';

vi.mock('$app/navigation', () => ({ goto: vi.fn(), beforeNavigate: vi.fn() }));
vi.mock('$app/state', () => ({ page: { params: { id: 'p1' } } }));
vi.mock('$lib/api', () => ({
	api: {
		me: vi.fn(),
		logout: vi.fn().mockResolvedValue(undefined),
		proofs: { get: vi.fn(), verify: vi.fn(), structure: vi.fn() },
		systems: { get: vi.fn() }
	},
	ApiError: class ApiError extends Error {}
}));

const apiMock = api as unknown as {
	me: ReturnType<typeof vi.fn>;
	logout: ReturnType<typeof vi.fn>;
	proofs: { get: ReturnType<typeof vi.fn> };
	systems: { get: ReturnType<typeof vi.fn> };
};

function detail(over: Partial<ProofDetail> = {}): ProofDetail {
	return {
		id: 'p1',
		name: 'sqrt2irr',
		slug: 'sqrt2irr',
		title: null,
		description: null,
		formal_system_id: 'sys1',
		folder_id: null,
		valid: true,
		published_at: '2020-01-01T00:00:00Z',
		created_at: '2020-01-01T00:00:00Z',
		updated_at: '2020-01-01T00:00:00Z',
		owner: null,
		source: 'x = x [HYP]',
		result: null,
		references: [],
		referenced_by: [],
		theorem: null,
		documentation: null,
		...over
	};
}

beforeEach(async () => {
	apiMock.logout.mockResolvedValue(undefined);
	apiMock.me.mockRejectedValue(new Error('anonymous'));
	apiMock.systems.get.mockRejectedValue(new Error('not readable'));
	await auth.refresh();
});
afterEach(async () => {
	await auth.logout();
	vi.clearAllMocks();
});

describe('the proof detail page', () => {
	it('shows the title under the name', async () => {
		apiMock.proofs.get.mockResolvedValue(
			detail({ title: 'The square root of 2 is irrational.' })
		);
		render(Page);

		await waitFor(() =>
			expect(screen.getByText('The square root of 2 is irrational.')).toBeInTheDocument()
		);
		expect(screen.getByRole('heading', { name: 'sqrt2irr' })).toBeInTheDocument();
	});

	it('keeps the description visible when a title is also set', async () => {
		// Both are settable through `ProofCreate`/`ProofUpdate`, and the header
		// shows one line. Preferring the title there must not make an author's own
		// description disappear from the page — so it gets a place of its own.
		apiMock.proofs.get.mockResolvedValue(
			detail({ title: 'A short title.', description: 'A longer account of what this proves.' })
		);
		render(Page);

		await waitFor(() => expect(screen.getByText('A short title.')).toBeInTheDocument());
		expect(screen.getByText('A longer account of what this proves.')).toBeInTheDocument();
	});

	it('does not repeat the description when it is what the header shows', async () => {
		// A proof with no title falls back to the description in the header, which
		// is how a hand-authored proof has always read. It must appear once.
		apiMock.proofs.get.mockResolvedValue(detail({ description: 'Only a description.' }));
		render(Page);

		await waitFor(() => expect(screen.getByText('Only a description.')).toBeInTheDocument());
		expect(screen.getAllByText('Only a description.')).toHaveLength(1);
	});

	it('shows the corpus record with its authorship', async () => {
		apiMock.proofs.get.mockResolvedValue(
			detail({
				title: 'The square root of 2 is irrational.',
				documentation: {
					label: 'sqrt2irr',
					title: 'The square root of 2 is irrational.',
					text: 'Theorem 1.10 of [Apostol] p. 28.',
					attributions: [{ kind: 'Contributed', who: 'NM', dated: '20-Aug-2001' }]
				}
			})
		);
		render(Page);

		await waitFor(() =>
			expect(screen.getByText('Theorem 1.10 of [Apostol] p. 28.')).toBeInTheDocument()
		);
		expect(screen.getByText(/Contributed/)).toBeInTheDocument();
		expect(screen.getByText(/NM, 20-Aug-2001/)).toBeInTheDocument();
	});
});
