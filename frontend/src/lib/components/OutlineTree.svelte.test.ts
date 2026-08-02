import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import OutlineTree from './OutlineTree.svelte';
import type { Folder } from '$lib/api';

const user = userEvent.setup();

function folder(over: Partial<Folder> = {}): Folder {
	return {
		id: over.name ?? 'f1',
		name: 'Part',
		slug: 'part',
		description: null,
		position: 0,
		proofs: 0,
		children: [],
		...over
	};
}

const TREE: Folder[] = [
	folder({
		name: 'LOGIC',
		description: 'What this part contains.',
		children: [
			folder({ name: 'Implication', proofs: 3 }),
			folder({ name: 'Afterwards', proofs: 1 })
		]
	})
];

describe('the outline tree', () => {
	it('shows roots and their children when opened by default', () => {
		render(OutlineTree, { folders: TREE, open: true });

		expect(screen.getByText('LOGIC')).toBeInTheDocument();
		expect(screen.getByText('Implication')).toBeInTheDocument();
		expect(screen.getByText('What this part contains.')).toBeInTheDocument();
	});

	it('keeps deeper levels closed until asked', async () => {
		// A corpus has hundreds of nodes; expanding everything on arrival would bury
		// the shape it exists to show.
		render(OutlineTree, { folders: TREE });
		expect(screen.queryByText('Implication')).not.toBeInTheDocument();

		await user.click(screen.getByRole('button', { name: 'Expand LOGIC' }));
		expect(screen.getByText('Implication')).toBeInTheDocument();

		await user.click(screen.getByRole('button', { name: 'Collapse LOGIC' }));
		expect(screen.queryByText('Implication')).not.toBeInTheDocument();
	});

	it('gives a leaf no expander', () => {
		render(OutlineTree, { folders: [folder({ name: 'Leaf' })] });
		expect(screen.queryByRole('button')).not.toBeInTheDocument();
	});

	it('shows a count only where proofs sit directly', () => {
		render(OutlineTree, { folders: TREE, open: true });
		// The part holds none itself — every proof is filed under the deepest
		// section covering it — so it shows no number at all rather than a zero.
		expect(screen.getByText('3')).toBeInTheDocument();
		expect(screen.queryByText('0')).not.toBeInTheDocument();
	});
});


describe('a long description', () => {
	it('is clamped and offered whole on hover', () => {
		// set.mm's part-level descriptions run to 27,820 characters between them and
		// one subsection's is 20,783 on its own. Unclamped they bury the tree.
		const long = 'A long section introduction. '.repeat(200);
		render(OutlineTree, { folders: [folder({ name: 'Part', description: long })] });

		const shown = screen.getByText(long.trim());
		expect(shown).toHaveClass('line-clamp-2');
		expect(shown).toHaveAttribute('title', long);
	});
});
