import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import ProofResults from './ProofResults.svelte';
import type { VerifyResponse } from '$lib/api';

const user = userEvent.setup();

function line(overrides: Record<string, unknown> = {}) {
	return {
		valid: true,
		number: 1,
		behaviour: 'logical',
		name: 'statement',
		invalid_message: null,
		warning_message: null,
		reference: null,
		label: null,
		display: 'x = x',
		indent: 0,
		...overrides
	};
}

function result(lines: ReturnType<typeof line>[]): VerifyResponse {
	return { success: true, errors: [], proof: { indicator: 'ok', lines } };
}

describe('ProofResults line interaction', () => {
	it('renders plain, non-interactive rows without onLineClick', () => {
		render(ProofResults, { result: result([line(), line()]) });
		expect(screen.queryByRole('button', { name: /Go to line/ })).toBeNull();
	});

	it('makes each row a button that reports its index when onLineClick is set', async () => {
		const onLineClick = vi.fn();
		render(ProofResults, {
			result: result([line({ display: 'a' }), line({ display: 'b' }), line({ display: 'c' })]),
			onLineClick
		});
		const buttons = screen.getAllByRole('button', { name: /Go to line/ });
		expect(buttons).toHaveLength(3);
		await user.click(screen.getByRole('button', { name: 'Go to line 2 in the editor' }));
		expect(onLineClick).toHaveBeenCalledExactlyOnceWith(1);
	});

	it('shows the idle message before any result', () => {
		render(ProofResults, { result: null, idleMessage: 'Start typing…' });
		expect(screen.getByText('Start typing…')).toBeInTheDocument();
	});
});

describe('ProofResults gutter numbering', () => {
	it('numbers by citation, leaving an unnumbered line blank', () => {
		// A blank line carries no citation number, so the steps around it keep the
		// numbers their references name. The gutter must show those, not the row
		// position — which here would misnumber both steps.
		render(ProofResults, {
			result: result([
				line({ number: null, display: '', behaviour: null, name: null }),
				line({ number: 1, display: 'a [HYP]' }),
				line({ number: 2, display: 'b [MP, 1]' })
			])
		});
		const gutter = screen
			.getAllByRole('listitem')
			.map((li) => li.querySelector('span')?.textContent?.trim());
		expect(gutter).toEqual(['', '1', '2']);
	});

	it('falls back to row position for a payload cached before numbering existed', () => {
		const stale = () => {
			const l = line();
			delete (l as Record<string, unknown>).number;
			return l;
		};
		render(ProofResults, { result: result([stale(), stale()]) });
		const gutter = screen
			.getAllByRole('listitem')
			.map((li) => li.querySelector('span')?.textContent?.trim());
		expect(gutter).toEqual(['1', '2']);
	});
});

describe('ProofResults line markers', () => {
	it('marks nothing on a valid line when the reader is not editing', () => {
		// A tick on every line of a valid proof is noise: the card's own badge
		// already says the proof checked.
		const { container } = render(ProofResults, {
			result: result([line(), line()]),
			verdicts: false
		});

		expect(container.querySelectorAll('svg.text-success')).toHaveLength(0);
	});

	it('keeps a tick per line while editing, where it is the feedback', () => {
		const { container } = render(ProofResults, { result: result([line(), line()]) });

		expect(container.querySelectorAll('svg.text-success')).toHaveLength(2);
	});

	it('marks an open goal apart from a wrong step', () => {
		// A hole is work left, not a mistake, and a cross over it reads as a step
		// that does not follow.
		const { container } = render(ProofResults, {
			result: result([
				line({ valid: false, failure: { code: 'hole', message: '' } }),
				line({ valid: false, invalid_message: 'MP does not apply.' })
			]),
			verdicts: false
		});

		expect(container.querySelectorAll('svg.text-muted-foreground')).toHaveLength(1);
		expect(container.querySelectorAll('svg.text-destructive')).toHaveLength(1);
	});
});

describe('ProofResults line types', () => {
	it('does not badge the type every ordinary line carries', () => {
		render(ProofResults, {
			result: result([line({ name: 'statement' })]),
			primaryLineType: 'statement'
		});

		expect(screen.queryByText('statement')).toBeNull();
	});

	it('badges a type that says something the formula does not', () => {
		render(ProofResults, {
			result: result([line({ name: 'assume', display: 'assume x ∈ y' })]),
			primaryLineType: 'statement'
		});

		expect(screen.getByText('assume')).toBeInTheDocument();
	});

	it('suppresses nothing until told which type is the default', () => {
		// The system may not have loaded, and a caller that has not said which type
		// is the default has not claimed any of them is — so this stays as it was.
		render(ProofResults, { result: result([line({ name: 'statement' })]) });

		expect(screen.getByText('statement')).toBeInTheDocument();
	});
});

describe('ProofResults citations', () => {
	it('shows the citation as plain text with no proof to explain it against', () => {
		// The editor's live results describe text that may not be what is stored,
		// so there is nothing to ask the server about.
		render(ProofResults, { result: result([line({ reference: 'MP, 1, 2' })]) });

		expect(screen.getByText('by MP, 1, 2')).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: /MP, 1, 2/ })).toBeNull();
	});

	it('makes the citation expandable once it belongs to a stored proof', () => {
		render(ProofResults, {
			result: result([line({ reference: 'MP, 1, 2' })]),
			proofId: 'p1'
		});

		expect(screen.getByRole('button', { name: /MP, 1, 2/ })).toBeInTheDocument();
	});
});
