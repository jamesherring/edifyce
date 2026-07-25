import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { createRawSnippet, tick } from 'svelte';
import PartSection from './PartSection.svelte';

// PartSection is generic over `T extends { id: string }`; render() resolves T to
// that constraint, so the test item is exactly `{ id }` (all the reorder logic
// needs). The caller-supplied `row` snippet decides what each row displays.
type Item = { id: string };

const rowSnippet = createRawSnippet<[Item]>((item) => ({
	render: () => `<span>row-${item().id}</span>`
}));

const items: Item[] = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];

function renderSection(overrides: Record<string, unknown> = {}) {
	const onReorder = vi.fn();
	const onAdd = vi.fn();
	const onEdit = vi.fn();
	render(PartSection, {
		title: 'Sorts',
		items,
		emptyMessage: 'No sorts yet.',
		row: rowSnippet,
		onReorder,
		onAdd,
		onEdit,
		...overrides
	});
	return { onReorder, onAdd, onEdit };
}

describe('PartSection', () => {
	it('renders each item through the row snippet', () => {
		renderSection();
		expect(screen.getByText('row-a')).toBeInTheDocument();
		expect(screen.getByText('row-b')).toBeInTheDocument();
		expect(screen.getByText('row-c')).toBeInTheDocument();
	});

	it('shows the empty message when there are no items', () => {
		renderSection({ items: [] });
		expect(screen.getByText('No sorts yet.')).toBeInTheDocument();
	});

	it('reorders by swapping the moved item down one place', async () => {
		const { onReorder } = renderSection();
		// One "Move down" button per row; the first row's swaps a↔b.
		await userEvent.click(screen.getAllByRole('button', { name: 'Move down' })[0]);
		expect(onReorder).toHaveBeenCalledWith(['b', 'a', 'c']);
	});

	it('reorders by swapping the moved item up one place', async () => {
		const { onReorder } = renderSection();
		// The last row's "Move up" swaps b↔c.
		const ups = screen.getAllByRole('button', { name: 'Move up' });
		await userEvent.click(ups[ups.length - 1]);
		expect(onReorder).toHaveBeenCalledWith(['a', 'c', 'b']);
	});

	it('disables moving the first item up and the last item down (no wrap)', () => {
		renderSection();
		expect(screen.getAllByRole('button', { name: 'Move up' })[0]).toBeDisabled();
		const downs = screen.getAllByRole('button', { name: 'Move down' });
		expect(downs[downs.length - 1]).toBeDisabled();
	});

	it('invokes onAdd when the add button is clicked', async () => {
		const { onAdd } = renderSection({ addLabel: 'Add sort' });
		await userEvent.click(screen.getByRole('button', { name: 'Add sort' }));
		expect(onAdd).toHaveBeenCalledOnce();
	});
});

/** The grip only arms the drag; jsdom has no drag machinery, so the events the
 *  browser would fire are dispatched directly. */
function drag(from: number, to: number) {
	const rows = screen.getAllByRole('listitem');
	const grip = rows[from].querySelector('[title="Drag to reorder"]')!;
	grip.dispatchEvent(new Event('pointerdown', { bubbles: true }));
	rows[from].dispatchEvent(new Event('dragstart', { bubbles: true }));
	rows[to].dispatchEvent(new Event('dragover', { bubbles: true, cancelable: true }));
	rows[to].dispatchEvent(new Event('drop', { bubbles: true, cancelable: true }));
}

describe('PartSection drag-and-drop reordering', () => {
	it('moves the dragged item to the drop position, shifting the rest', () => {
		const { onReorder } = renderSection();
		drag(0, 2);
		expect(onReorder).toHaveBeenCalledWith(['b', 'c', 'a']);
	});

	it('moves an item upwards the same way', () => {
		const { onReorder } = renderSection();
		drag(2, 0);
		expect(onReorder).toHaveBeenCalledWith(['c', 'a', 'b']);
	});

	it('does nothing when a row is dropped on itself', () => {
		const { onReorder } = renderSection();
		drag(1, 1);
		expect(onReorder).not.toHaveBeenCalled();
	});

	it('does not reorder while a previous reorder is still in flight', () => {
		const { onReorder } = renderSection({ busy: true });
		drag(0, 2);
		expect(onReorder).not.toHaveBeenCalled();
	});

	it('only becomes draggable once the grip is pressed', async () => {
		renderSection();
		const row = screen.getAllByRole('listitem')[0];
		// Rows carry formulas worth selecting, so they aren't draggable by default.
		expect(row.getAttribute('draggable')).toBe('false');
		row
			.querySelector('[title="Drag to reorder"]')!
			.dispatchEvent(new Event('pointerdown', { bubbles: true }));
		await tick();
		expect(row.getAttribute('draggable')).toBe('true');
	});

	it('keeps the grip out of the accessibility tree, leaving the chevrons as the keyboard path', () => {
		renderSection();
		const grip = screen.getAllByRole('listitem')[0].querySelector('[title="Drag to reorder"]')!;
		expect(grip).toHaveAttribute('aria-hidden', 'true');
		expect(grip.tagName.toLowerCase()).toBe('span');
	});
});
