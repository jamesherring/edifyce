import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import Page from './+page.svelte';
import { api, ApiError } from '$lib/api';
import type { Assumption } from '$lib/api';

vi.mock('$lib/api', () => ({
	api: { assumptions: { public: vi.fn() } },
	ApiError: class ApiError extends Error {
		status: number;
		constructor(status: number, detail: unknown, message?: string) {
			super(message ?? String(detail));
			this.status = status;
		}
	}
}));

const apiMock = api as unknown as { assumptions: { public: ReturnType<typeof vi.fn> } };

function assumption(over: Partial<Assumption> = {}): Assumption {
	return {
		id: 'a1',
		label: 'lemma-2-1',
		statement: '(p → p)',
		reason: 'Standard, proof omitted.',
		source: null,
		formal_system_id: 'sys1',
		formal_system_name: 'Set theory',
		dependents: 0,
		created_at: '2026-01-01T00:00:00Z',
		...over
	};
}

beforeEach(() => {
	vi.clearAllMocks();
});

describe('the public gap register', () => {
	it('ranks by how much rests on each one and links to its page', async () => {
		apiMock.assumptions.public.mockResolvedValue({
			items: [assumption({ dependents: 97 })],
			total: 1,
			limit: 20,
			offset: 0
		});
		render(Page);

		expect(await screen.findByText('97 dependents')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /lemma-2-1/ })).toHaveAttribute(
			'href',
			'/systems/sys1/assumptions/lemma-2-1'
		);
	});

	it('drops a row the next page repeats', async () => {
		// Offset paging over a set that can change between requests: a row shifting
		// across the boundary arrives twice, and twice under one key throws.
		apiMock.assumptions.public
			.mockResolvedValueOnce({
				items: [assumption({ id: 'a1' }), assumption({ id: 'a2', label: 'lemma-2-2' })],
				total: 3,
				limit: 20,
				offset: 0
			})
			.mockResolvedValueOnce({
				items: [assumption({ id: 'a2', label: 'lemma-2-2' }), assumption({ id: 'a3', label: 'lemma-2-3' })],
				total: 3,
				limit: 20,
				offset: 2
			});
		render(Page);

		await userEvent.click(await screen.findByRole('button', { name: 'Show more' }));

		expect(await screen.findByRole('link', { name: /lemma-2-3/ })).toBeInTheDocument();
		// Three distinct rows, not four: the repeat is dropped rather than listed
		// twice (or, keyed, thrown over).
		expect(screen.getAllByRole('link')).toHaveLength(3);
		expect(screen.getAllByRole('link', { name: /lemma-2-2/ })).toHaveLength(1);
	});

	it('keeps the rows it has when a later page fails, and offers a retry', async () => {
		apiMock.assumptions.public
			.mockResolvedValueOnce({ items: [assumption()], total: 2, limit: 20, offset: 0 })
			.mockRejectedValueOnce(new ApiError(500, 'upstream is down'));
		render(Page);

		await userEvent.click(await screen.findByRole('button', { name: 'Show more' }));

		expect(await screen.findByText('upstream is down')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /lemma-2-1/ })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
	});

	it('does not claim nothing is assumed when the first page failed', async () => {
		apiMock.assumptions.public.mockRejectedValue(new ApiError(500, 'upstream is down'));
		render(Page);

		expect(await screen.findByText('upstream is down')).toBeInTheDocument();
		expect(screen.queryByText('Nothing is assumed')).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
	});
});
