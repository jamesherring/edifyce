import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import EditPage from './+page.svelte';
import { page } from '$lib/testing/page-mock.svelte';
import { auth } from '$lib/auth.svelte';
import { api } from '$lib/api';

vi.mock('$app/state', async () => await import('$lib/testing/page-mock.svelte'));
vi.mock('$app/navigation', () => ({ goto: vi.fn(), beforeNavigate: vi.fn() }));
// Every part section grabs its `api.parts.<x>` crud object at init, so the mock
// has to expose them even though this file never saves a part.
vi.mock('$lib/api', () => {
	const partStub = () => ({ create: vi.fn(), update: vi.fn(), remove: vi.fn(), reorder: vi.fn() });
	return {
		api: {
			me: vi.fn(),
			systems: { get: vi.fn(), validate: vi.fn(), update: vi.fn() },
			parts: {
				sorts: partStub(),
				productions: partStub(),
				brackets: partStub(),
				lineTypes: partStub(),
				definitions: partStub(),
				axioms: partStub(),
				rules: partStub()
			}
		},
		ApiError: class ApiError extends Error {}
	};
});
vi.mock('$lib/toast', () => ({ toastSuccess: vi.fn(), toastError: vi.fn() }));

const apiMock = api as unknown as {
	me: ReturnType<typeof vi.fn>;
	systems: {
		get: ReturnType<typeof vi.fn>;
		validate: ReturnType<typeof vi.fn>;
		update: ReturnType<typeof vi.fn>;
	};
};

const USER = {
	id: 'u1',
	email: 'a@b.c',
	is_active: true,
	is_superuser: false,
	is_verified: true,
	display_name: 'Ada'
};

function makeSystem(over: Record<string, unknown> = {}) {
	return {
		id: 'S',
		name: 'Sigma',
		slug: 'sigma',
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
		rules: [],
		notations: ['latex', 'unicode'],
		default_notation: null,
		...over
	};
}

/** The picker's trigger, once the page has finished loading the system. */
async function picker() {
	return await screen.findByRole('combobox', { name: 'Opens in' });
}

async function pick(label: string) {
	await userEvent.click(await picker());
	await userEvent.click(await screen.findByText(label));
}

beforeEach(async () => {
	apiMock.me.mockResolvedValue(USER);
	await auth.refresh(); // sign in so the owner can edit
	apiMock.systems.validate.mockResolvedValue({
		success: true,
		errors: [],
		system_name: 'Sigma',
		line_type_count: 0,
		inference_rule_count: 0
	});
	page.params.id = '';
});
afterEach(() => vi.clearAllMocks());

describe('the system’s reading setting', () => {
	it('opens showing the stored reading rather than Automatic', async () => {
		apiMock.systems.get.mockResolvedValue(makeSystem({ default_notation: 'unicode' }));
		page.params.id = 'S';
		render(EditPage);

		await waitFor(async () => expect(await picker()).toHaveTextContent('unicode'));
	});

	it('saves the chosen reading, sending the notation’s own name', async () => {
		apiMock.systems.get.mockResolvedValue(makeSystem());
		apiMock.systems.update.mockResolvedValue(makeSystem({ default_notation: 'latex' }));
		page.params.id = 'S';
		render(EditPage);

		await picker();
		await pick('latex');

		// The picker's value is namespaced so its sentinel cannot collide with a
		// notation name; what reaches the API is the bare name.
		expect(apiMock.systems.update).toHaveBeenCalledWith('S', { default_notation: 'latex' });
		await waitFor(async () => expect(await picker()).toHaveTextContent('latex'));
	});

	it('clears the setting when Automatic is chosen', async () => {
		apiMock.systems.get.mockResolvedValue(makeSystem({ default_notation: 'latex' }));
		apiMock.systems.update.mockResolvedValue(makeSystem({ default_notation: null }));
		page.params.id = 'S';
		render(EditPage);

		await picker();
		await pick('Automatic');

		expect(apiMock.systems.update).toHaveBeenCalledWith('S', { default_notation: null });
	});

	it('puts the picker back to the stored reading when the save is refused', async () => {
		// The combobox owns what it displays once bound, so a refusal that left the
		// rejected reading up would show a setting the server never took.
		apiMock.systems.get.mockResolvedValue(makeSystem({ default_notation: 'unicode' }));
		apiMock.systems.update.mockRejectedValue(new Error('nope'));
		page.params.id = 'S';
		render(EditPage);

		await waitFor(async () => expect(await picker()).toHaveTextContent('unicode'));
		await pick('latex');

		expect(apiMock.systems.update).toHaveBeenCalled();
		await waitFor(async () => expect(await picker()).toHaveTextContent('unicode'));
	});

	it('keeps a stored reading clearable when the system has no notations left', async () => {
		// Otherwise the card hides and the stale value is stranded off-screen.
		apiMock.systems.get.mockResolvedValue(
			makeSystem({ notations: [], default_notation: 'unicode' })
		);
		page.params.id = 'S';
		render(EditPage);

		await waitFor(async () => expect(await picker()).toBeInTheDocument());
	});

	it('offers no reading card at all for a system with nothing to read through', async () => {
		apiMock.systems.get.mockResolvedValue(makeSystem({ notations: [], default_notation: null }));
		page.params.id = 'S';
		render(EditPage);

		await waitFor(() => expect(screen.getByText('Sigma')).toBeInTheDocument());
		expect(screen.queryByRole('combobox', { name: 'Opens in' })).toBeNull();
	});
});
