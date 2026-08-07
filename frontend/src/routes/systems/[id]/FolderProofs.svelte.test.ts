import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import FolderProofs from './FolderProofs.svelte';
import { api } from '$lib/api';
import type { Folder, ProofSummary } from '$lib/api';

vi.mock('$lib/api', () => ({
	api: { proofs: { listPublic: vi.fn() } },
	ApiError: class ApiError extends Error {}
}));

const listPublic = (api as unknown as { proofs: { listPublic: ReturnType<typeof vi.fn> } })
	.proofs.listPublic;

const user = userEvent.setup();

function summary(over: Partial<ProofSummary> = {}): ProofSummary {
	return {
		id: over.name ?? 'p1',
		name: 'id',
		slug: 'id',
		title: null,
		description: null,
		formal_system_id: 'sys1',
		folder_id: 'f1',
		valid: true,
		published_at: '2020-01-01T00:00:00Z',
		created_at: '2020-01-01T00:00:00Z',
		updated_at: '2020-01-01T00:00:00Z',
		owner: null,
		...over
	};
}

const FOLDER: Folder = {
	id: 'f1',
	name: 'Implication',
	slug: 'implication',
	description: null,
	position: 0,
	proofs: 2,
	children: []
};

afterEach(() => vi.clearAllMocks());

describe('the proofs of one section', () => {
	it('lists what the folder holds', async () => {
		listPublic.mockResolvedValue({
			items: [summary({ name: 'id', title: 'The identity.' })],
			total: 1,
			limit: 25,
			offset: 0
		});
		render(FolderProofs, { systemId: 'sys1', folder: FOLDER });

		await waitFor(() => expect(screen.getByText('id')).toBeInTheDocument());
		expect(screen.getByText('The identity.')).toBeInTheDocument();
		expect(screen.getByText('1 proof')).toBeInTheDocument();
		expect(listPublic).toHaveBeenCalledWith(
			{ limit: 25, offset: 0 },
			{ formalSystemId: 'sys1', folderId: 'f1' }
		);
	});

	it('keeps the rows it has when a later page fails', async () => {
		// The only way back to a discarded first page is to reselect the folder, so
		// a failed "show more" must not take the list with it.
		listPublic.mockResolvedValueOnce({
			items: [summary({ name: 'id' })],
			total: 2,
			limit: 1,
			offset: 0
		});
		render(FolderProofs, { systemId: 'sys1', folder: FOLDER });
		await waitFor(() => expect(screen.getByText('id')).toBeInTheDocument());

		listPublic.mockRejectedValueOnce(new Error('the network went away'));
		await user.click(screen.getByRole('button', { name: /Show more/ }));

		await waitFor(() =>
			expect(screen.getByText(/the network went away/)).toBeInTheDocument()
		);
		expect(screen.getByText('id')).toBeInTheDocument();
	});

	it('says nothing is published rather than flashing it while loading', async () => {
		// The first fetch is queued by an effect that runs after the first render,
		// so an initial `loading = false` would paint the empty state over a full
		// section for a frame.
		let settle: (value: unknown) => void = () => {};
		listPublic.mockReturnValue(new Promise((resolve) => (settle = resolve)));
		render(FolderProofs, { systemId: 'sys1', folder: FOLDER });

		expect(screen.queryByText('Nothing published in this section.')).not.toBeInTheDocument();

		settle({ items: [], total: 0, limit: 25, offset: 0 });
		await waitFor(() =>
			expect(screen.getByText('Nothing published in this section.')).toBeInTheDocument()
		);
	});
});
