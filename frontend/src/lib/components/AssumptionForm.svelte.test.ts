import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import AssumptionForm from './AssumptionForm.svelte';
import { api } from '$lib/api';

vi.mock('$lib/api', () => ({
	api: { assumptions: { create: vi.fn() } },
	ApiError: class ApiError extends Error {}
}));

const apiMock = api as unknown as { assumptions: { create: ReturnType<typeof vi.fn> } };

beforeEach(() => {
	vi.clearAllMocks();
});

async function fillTheMinimum() {
	await userEvent.type(screen.getByLabelText('Label'), 'lemma-2-1');
	await userEvent.type(screen.getByLabelText('Statement'), '(p → p)');
	await userEvent.type(screen.getByLabelText('Reason'), 'Standard, proof omitted.');
}

describe('taking an assumption on', () => {
	it('refuses to submit without a reason', async () => {
		render(AssumptionForm, { systemId: 'sys1', oncreated: vi.fn(), oncancel: vi.fn() });

		await userEvent.type(screen.getByLabelText('Label'), 'lemma-2-1');
		await userEvent.type(screen.getByLabelText('Statement'), '(p → p)');

		// An assumption with no reason is an axiom nobody remembers adopting.
		expect(screen.getByRole('button', { name: 'Take on' })).toBeDisabled();

		await userEvent.type(screen.getByLabelText('Reason'), 'Standard, proof omitted.');
		expect(screen.getByRole('button', { name: 'Take on' })).toBeEnabled();
	});

	it('sends the label, statement and reason, and a null source when blank', async () => {
		apiMock.assumptions.create.mockResolvedValue({ id: 'a1', label: 'lemma-2-1' });
		const oncreated = vi.fn();
		render(AssumptionForm, { systemId: 'sys1', oncreated, oncancel: vi.fn() });

		await fillTheMinimum();
		await userEvent.click(screen.getByRole('button', { name: 'Take on' }));

		await waitFor(() => expect(apiMock.assumptions.create).toHaveBeenCalled());
		expect(apiMock.assumptions.create).toHaveBeenCalledWith('sys1', {
			label: 'lemma-2-1',
			statement: '(p → p)',
			premises: [],
			metavariables: {},
			distinct: [],
			reason: 'Standard, proof omitted.',
			source: null
		});
		expect(oncreated).toHaveBeenCalledWith({ id: 'a1', label: 'lemma-2-1' });
	});

	it('drops the rows left blank', async () => {
		apiMock.assumptions.create.mockResolvedValue({ id: 'a1' });
		render(AssumptionForm, { systemId: 'sys1', oncreated: vi.fn(), oncancel: vi.fn() });

		await fillTheMinimum();
		// Two premise rows, one of them never filled in — an added-then-abandoned
		// row is the ordinary way to leave one, and sending "" would be a premise
		// no citation could ever supply.
		await userEvent.click(screen.getByRole('button', { name: 'Add premise' }));
		await userEvent.click(screen.getByRole('button', { name: 'Add premise' }));
		await userEvent.type(screen.getAllByPlaceholderText('e.g. p')[0], 'q');
		await userEvent.click(screen.getByRole('button', { name: 'Add metavariable' }));

		await userEvent.click(screen.getByRole('button', { name: 'Take on' }));

		await waitFor(() => expect(apiMock.assumptions.create).toHaveBeenCalled());
		const [, payload] = apiMock.assumptions.create.mock.calls[0];
		expect(payload.premises).toEqual(['q']);
		// A metavariable needs both halves to mean anything.
		expect(payload.metavariables).toEqual({});
	});

	it('does not submit when Enter is pressed in the symbol palette’s search box', async () => {
		// The palette's search box is a text input. Inside the form it would be a
		// form control, and Enter in a form with a submit button submits it — POSTing
		// a half-written assumption. It lives outside the form for that reason, and
		// still types into the form's fields.
		apiMock.assumptions.create.mockResolvedValue({ id: 'a1' });
		render(AssumptionForm, { systemId: 'sys1', oncreated: vi.fn(), oncancel: vi.fn() });

		// Filled first, or `save` would refuse on its own and the test would pass
		// whichever side of the form the palette sat on.
		await fillTheMinimum();
		await userEvent.click(screen.getByRole('button', { name: /symbol/i }));
		await userEvent.type(screen.getByPlaceholderText(/Search symbols/i), 'subset{Enter}');

		expect(apiMock.assumptions.create).not.toHaveBeenCalled();
	});

	it('leaves the form usable after a success, rather than stuck on "Taking on…"', async () => {
		// A host that keeps the form mounted — and `oncreated` runs outside the try,
		// so a throw from it can never be reported as the API refusing an assumption
		// that was in fact created.
		apiMock.assumptions.create.mockResolvedValue({ id: 'a1' });
		render(AssumptionForm, { systemId: 'sys1', oncreated: vi.fn(), oncancel: vi.fn() });

		await fillTheMinimum();
		await userEvent.click(screen.getByRole('button', { name: 'Take on' }));

		await waitFor(() =>
			expect(screen.getByRole('button', { name: 'Take on' })).toBeEnabled()
		);
	});

	it('shows the API refusal verbatim and stays open', async () => {
		apiMock.assumptions.create.mockRejectedValue(
			new Error("'lemma-2-1' already names a theorem in this system's library.")
		);
		const oncreated = vi.fn();
		render(AssumptionForm, { systemId: 'sys1', oncreated, oncancel: vi.fn() });

		await fillTheMinimum();
		await userEvent.click(screen.getByRole('button', { name: 'Take on' }));

		expect(await screen.findByText(/already names a theorem/)).toBeInTheDocument();
		expect(oncreated).not.toHaveBeenCalled();
		expect(screen.getByRole('button', { name: 'Take on' })).toBeEnabled();
	});
});
