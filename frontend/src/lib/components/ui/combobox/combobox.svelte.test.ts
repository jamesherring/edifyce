import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { Combobox, type ComboboxOption } from './index.js';

const options: ComboboxOption[] = [
	{ value: '1', label: 'Alpha', hint: 'published' },
	{ value: '2', label: 'Beta', hint: 'draft' },
	{ value: '3', label: 'Gamma' }
];

afterEach(() => vi.clearAllMocks());

describe('Combobox', () => {
	it('shows the placeholder until a value is selected', () => {
		render(Combobox, { options, placeholder: 'Pick one…' });
		expect(screen.getByRole('combobox')).toHaveTextContent('Pick one…');
	});

	it('opens on click and filters options by the search query', async () => {
		render(Combobox, { options });
		await userEvent.click(screen.getByRole('combobox'));

		// All options visible initially.
		expect(await screen.findByText('Alpha')).toBeInTheDocument();
		expect(screen.getByText('Beta')).toBeInTheDocument();

		// Typing narrows the list.
		await userEvent.type(screen.getByPlaceholderText('Search…'), 'gam');
		await waitForGone('Alpha');
		expect(screen.getByText('Gamma')).toBeInTheDocument();
	});

	it('emits the chosen value and reflects it on the trigger', async () => {
		const onSelect = vi.fn();
		render(Combobox, { options, onSelect });
		await userEvent.click(screen.getByRole('combobox'));
		await userEvent.click(await screen.findByText('Beta'));
		expect(onSelect).toHaveBeenCalledWith('2');
		expect(screen.getByRole('combobox')).toHaveTextContent('Beta');
	});
});

async function waitForGone(text: string) {
	const { waitFor } = await import('@testing-library/svelte');
	await waitFor(() => expect(screen.queryByText(text)).not.toBeInTheDocument());
}
