import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import LemmasPanel from './LemmasPanel.svelte';
import { api } from '$lib/api';
import type { ProofDetail, ProofSummary } from '$lib/api';

vi.mock('$lib/api', () => ({
	api: {
		proofs: { list: vi.fn(), setReferences: vi.fn() },
		systems: { get: vi.fn() }
	},
	ApiError: class ApiError extends Error {}
}));
vi.mock('$lib/toast', () => ({ toastSuccess: vi.fn(), toastError: vi.fn() }));

const apiMock = api as unknown as {
	proofs: { list: ReturnType<typeof vi.fn>; setReferences: ReturnType<typeof vi.fn> };
	systems: { get: ReturnType<typeof vi.fn> };
};

function summary(id: string, name: string, published = false): ProofSummary {
	return {
		id,
		name,
		slug: name.toLowerCase(),
		description: null,
		formal_system_id: 'sys1',
		folder_id: null,
		valid: null,
		published_at: published ? '2026-01-01T00:00:00Z' : null,
		created_at: '2026-01-01T00:00:00Z',
		updated_at: '2026-01-01T00:00:00Z',
		owner: null
	};
}

function detail(references: ProofDetail['references'] = []): ProofDetail {
	return {
		...summary('self', 'Main'),
		source: '',
		result: null,
		references,
		referenced_by: []
	};
}

// A line type whose reference field (the `<reference>` part) has the given regex.
function systemWithReferenceRegex(regex: string) {
	return {
		id: 'sys1',
		lines: [
			{
				id: 'l1',
				name: 'statement',
				shape: '<formula> [<reference>]',
				logical_sort: 'formula',
				parts: [{ id: 'p1', name: 'reference', regex }]
			}
		]
	};
}

// A system whose reference field admits a `.` — the happy path (no warning).
const dottedSystem = systemWithReferenceRegex('[A-Za-z0-9 ,.]+');

beforeEach(() => {
	apiMock.proofs.list.mockResolvedValue({
		items: [summary('lemA', 'Lemma A'), summary('lemB', 'Lemma B')],
		total: 2,
		limit: 100,
		offset: 0
	});
	apiMock.systems.get.mockResolvedValue(dottedSystem);
	apiMock.proofs.setReferences.mockImplementation(async (_id: string, references) =>
		detail(
			references.map((r: { referenced_proof_id: string; alias: string }) => ({
				referenced_proof_id: r.referenced_proof_id,
				alias: r.alias,
				name: r.referenced_proof_id === 'lemA' ? 'Lemma A' : 'Lemma B',
				slug: 'x',
				published: false
			}))
		)
	);
});
afterEach(() => vi.clearAllMocks());

describe('LemmasPanel', () => {
	it('lists existing references as citable rows', () => {
		render(LemmasPanel, {
			proof: detail([
				{ referenced_proof_id: 'lemA', alias: 'A', name: 'Lemma A', slug: 'lemma-a', published: false }
			])
		});
		expect(screen.getByText('Lemma A')).toBeInTheDocument();
		expect(screen.getByText('[A.line]')).toBeInTheDocument();
	});

	it('adds a picked lemma and saves the reference set', async () => {
		const onUpdated = vi.fn();
		render(LemmasPanel, { proof: detail(), onUpdated });

		// Open the picker and choose Lemma A.
		await userEvent.click(screen.getByRole('combobox'));
		await userEvent.click(await screen.findByText('Lemma A'));

		// A row now exists with a suggested alias; Save persists it.
		await userEvent.click(screen.getByRole('button', { name: 'Save references' }));

		await waitFor(() => expect(apiMock.proofs.setReferences).toHaveBeenCalledTimes(1));
		const [, refs] = apiMock.proofs.setReferences.mock.calls[0];
		expect(refs).toEqual([{ referenced_proof_id: 'lemA', alias: 'lemma-a' }]);
		expect(onUpdated).toHaveBeenCalledOnce();
	});

	it('pages through all candidates so lemmas past the first page are selectable', async () => {
		// A system with more than one page of proofs: the server caps a page at 100,
		// so the picker must walk the pages or later lemmas are unreachable.
		const firstPage = Array.from({ length: 100 }, (_, i) => summary(`p${i}`, `Proof ${i}`));
		const secondPage = [summary('deep', 'Deep Lemma')];
		apiMock.proofs.list.mockImplementation(async (_sys: string, params?: { offset?: number }) =>
			(params?.offset ?? 0) === 0
				? { items: firstPage, total: 101, limit: 100, offset: 0 }
				: { items: secondPage, total: 101, limit: 100, offset: 100 }
		);
		render(LemmasPanel, { proof: detail() });

		await userEvent.click(screen.getByRole('combobox'));
		// The second-page lemma is present and pickable via search.
		await userEvent.type(screen.getByPlaceholderText('Search proofs…'), 'Deep');
		expect(await screen.findByText('Deep Lemma')).toBeInTheDocument();
		expect(apiMock.proofs.list).toHaveBeenCalledTimes(2);
	});

	it('warns when the system reference field does not allow a dot', async () => {
		apiMock.systems.get.mockResolvedValue(systemWithReferenceRegex('[A-Za-z0-9 ,]+'));
		render(LemmasPanel, {
			proof: detail([
				{ referenced_proof_id: 'lemA', alias: 'A', name: 'Lemma A', slug: 'lemma-a', published: false }
			])
		});
		expect(await screen.findByText(/won't parse/)).toBeInTheDocument();
	});

	it('still warns when a permissive non-reference part could mask the check', async () => {
		// The reference field forbids `.`, but a later free-text `note` part accepts
		// anything. The warning must key off the reference field (the first
		// part-named placeholder), not any permissive part.
		apiMock.systems.get.mockResolvedValue({
			id: 'sys1',
			lines: [
				{
					id: 'l1',
					name: 'statement',
					shape: '<formula> [<reference>] <note>',
					logical_sort: 'formula',
					parts: [
						{ id: 'p1', name: 'reference', regex: '[A-Za-z0-9 ,]+' },
						{ id: 'p2', name: 'note', regex: '.*' }
					]
				}
			]
		});
		render(LemmasPanel, {
			proof: detail([
				{ referenced_proof_id: 'lemA', alias: 'A', name: 'Lemma A', slug: 'lemma-a', published: false }
			])
		});
		expect(await screen.findByText(/won't parse/)).toBeInTheDocument();
	});

	it('does not warn when the reference field allows a dot', async () => {
		render(LemmasPanel, {
			proof: detail([
				{ referenced_proof_id: 'lemA', alias: 'A', name: 'Lemma A', slug: 'lemma-a', published: false }
			])
		});
		await waitFor(() => expect(apiMock.systems.get).toHaveBeenCalled());
		expect(screen.queryByText(/won't parse/)).not.toBeInTheDocument();
	});
});
