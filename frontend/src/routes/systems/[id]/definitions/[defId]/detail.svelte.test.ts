import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import Page from './+page.svelte';
import { page } from '$lib/testing/page-mock.svelte';
import { api } from '$lib/api';
import type { Definition, FormalSystemDetail } from '$lib/api';

vi.mock('$app/state', async () => await import('$lib/testing/page-mock.svelte'));
vi.mock('$lib/api', () => ({
	api: { systems: { get: vi.fn() } },
	ApiError: class ApiError extends Error {}
}));

const apiMock = api as unknown as { systems: { get: ReturnType<typeof vi.fn> } };

function definition(over: Partial<Definition> = {}): Definition {
	return {
		id: 'd1',
		sort: 'formula',
		name: 'subset',
		higher: 'x ⊆ y',
		lower: '∀z (z ∈ x → z ∈ y)',
		provisos: ['disjoint(x, y)'],
		condition: 'disjoint(x, y)',
		bindings: [{ var: 'x', sort: 'variable' }],
		fresh: [{ var: 'z', sort: 'variable' }],
		label: null,
		justification: null,
		...over
	};
}

function system(definitions: Definition[]): FormalSystemDetail {
	return {
		id: 'sys1',
		name: 'Set theory',
		slug: 'set-theory',
		description: null,
		inherits_from_id: null,
		token_separated: false,
		published_at: '2026-01-01T00:00:00Z',
		created_at: '2026-01-01T00:00:00Z',
		updated_at: '2026-01-01T00:00:00Z',
		owner: null,
		brackets: [],
		sorts: [],
		productions: [],
		lines: [],
		definitions,
		axioms: [],
		rules: []
	};
}

beforeEach(() => {
	page.params = { id: 'sys1', defId: 'd1' };
	vi.clearAllMocks();
});

describe('definition detail page', () => {
	it('renders the definition with its fresh vars and provisos', async () => {
		apiMock.systems.get.mockResolvedValue(system([definition()]));
		render(Page);

		expect(await screen.findByRole('heading', { name: 'subset' })).toBeInTheDocument();
		expect(screen.getByText('∀z (z ∈ x → z ∈ y)')).toBeInTheDocument();
		expect(screen.getByText('Bound variables (fresh)')).toBeInTheDocument();
		expect(screen.getByText('z : variable')).toBeInTheDocument();
		expect(screen.getByText('disjoint(x, y)')).toBeInTheDocument();
	});

	it('shows an error when the definition is absent from the system', async () => {
		apiMock.systems.get.mockResolvedValue(system([definition({ id: 'other' })]));
		render(Page);

		expect(await screen.findByText(/does not exist in this system/)).toBeInTheDocument();
	});
});
