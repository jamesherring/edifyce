import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import Page from './+page.svelte';
import { page } from '$lib/testing/page-mock.svelte';
import { auth } from '$lib/auth.svelte';
import { api } from '$lib/api';
import type { Assumption } from '$lib/api';

vi.mock('$app/state', async () => await import('$lib/testing/page-mock.svelte'));
vi.mock('$app/navigation', () => ({ goto: vi.fn(), beforeNavigate: vi.fn() }));
vi.mock('$lib/api', () => ({
	api: {
		me: vi.fn(),
		logout: vi.fn().mockResolvedValue(undefined),
		systems: { get: vi.fn() },
		assumptions: { list: vi.fn(), withdraw: vi.fn(), create: vi.fn() }
	},
	ApiError: class ApiError extends Error {
		status: number;
		constructor(status: number, message: string) {
			super(message);
			this.status = status;
		}
	}
}));

const apiMock = api as unknown as {
	me: ReturnType<typeof vi.fn>;
	logout: ReturnType<typeof vi.fn>;
	systems: { get: ReturnType<typeof vi.fn> };
	assumptions: {
		list: ReturnType<typeof vi.fn>;
		withdraw: ReturnType<typeof vi.fn>;
		create: ReturnType<typeof vi.fn>;
	};
};

const OWNER = { id: 'u1', email: 'owner@example.com', display_name: 'Owner' };

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

function ownedSystem() {
	return { id: 'sys1', name: 'Set theory', owner: OWNER };
}

beforeEach(async () => {
	page.params = { id: 'sys1' };
	apiMock.systems.get.mockResolvedValue(ownedSystem());
	apiMock.assumptions.list.mockResolvedValue([assumption()]);
	apiMock.me.mockResolvedValue(OWNER);
	await auth.refresh();
});

afterEach(async () => {
	await auth.logout();
	vi.clearAllMocks();
});

describe("a system's assumptions", () => {
	it('lists each one with its blast radius', async () => {
		apiMock.assumptions.list.mockResolvedValue([assumption({ dependents: 12 })]);
		render(Page);

		expect(await screen.findByRole('link', { name: 'lemma-2-1' })).toHaveAttribute(
			'href',
			'/systems/sys1/assumptions/lemma-2-1'
		);
		expect(screen.getByText('12 dependents')).toBeInTheDocument();
	});

	it('offers withdrawal to the owner only', async () => {
		render(Page);
		expect(await screen.findByRole('button', { name: 'Withdraw' })).toBeInTheDocument();

		await auth.logout();
		await waitFor(() =>
			expect(screen.queryByRole('button', { name: 'Withdraw' })).not.toBeInTheDocument()
		);
	});

	it('drops a withdrawn assumption from the list', async () => {
		apiMock.assumptions.withdraw.mockResolvedValue(undefined);
		render(Page);

		await userEvent.click(await screen.findByRole('button', { name: 'Withdraw' }));

		expect(apiMock.assumptions.withdraw).toHaveBeenCalledWith('sys1', 'lemma-2-1');
		await waitFor(() =>
			expect(screen.queryByRole('link', { name: 'lemma-2-1' })).not.toBeInTheDocument()
		);
	});

	it('keeps the row and names the dependents when withdrawal is refused', async () => {
		// The one refusal worth reading in full: dropping a debt something rests on
		// would leave those entries citable and reporting no assumptions.
		const { ApiError } = await import('$lib/api');
		apiMock.assumptions.withdraw.mockRejectedValue(
			new ApiError(409, "'lemma-2-1' cannot be withdrawn while 'thm-3' rests on it")
		);
		render(Page);

		await userEvent.click(await screen.findByRole('button', { name: 'Withdraw' }));

		expect(await screen.findByText(/'thm-3' rests on it/)).toBeInTheDocument();
		expect(screen.getByRole('link', { name: 'lemma-2-1' })).toBeInTheDocument();
	});

	it('says so plainly when a system assumes nothing', async () => {
		apiMock.assumptions.list.mockResolvedValue([]);
		render(Page);

		expect(await screen.findByText(/This system assumes nothing/)).toBeInTheDocument();
	});
});
