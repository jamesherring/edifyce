import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import BindingsEditor from './BindingsEditor.svelte';

// Exercises the RepeatableRows mechanism through a real consumer: the row fields
// bind to `item.<field>` (a snippet parameter), and add/remove mutate the list.
describe('BindingsEditor (RepeatableRows)', () => {
	it('renders one var+sort input pair per binding', () => {
		render(BindingsEditor, { bindings: [{ var: 'p', sort: 'formula' }] });
		expect(screen.getByDisplayValue('p')).toBeInTheDocument();
		expect(screen.getByDisplayValue('formula')).toBeInTheDocument();
	});

	it('binds typing back onto the row object (bind through the snippet param)', async () => {
		const bindings = [{ var: '', sort: '' }];
		render(BindingsEditor, { bindings });
		const [varInput, sortInput] = screen.getAllByRole('textbox');

		await userEvent.type(varInput, 'x');
		await userEvent.type(sortInput, 'term');

		// The same object the caller passed is mutated in place.
		expect(bindings[0]).toEqual({ var: 'x', sort: 'term' });
	});

	it('adds a blank row and removes a row', async () => {
		render(BindingsEditor, { bindings: [{ var: 'a', sort: 'term' }] });
		expect(screen.getAllByRole('textbox')).toHaveLength(2); // one pair

		await userEvent.click(screen.getByRole('button', { name: 'Add binding' }));
		expect(screen.getAllByRole('textbox')).toHaveLength(4); // two pairs

		await userEvent.click(screen.getAllByRole('button', { name: 'Remove binding' })[0]);
		expect(screen.getAllByRole('textbox')).toHaveLength(2);
	});
});
