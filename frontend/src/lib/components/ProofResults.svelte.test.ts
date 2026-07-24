import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import ProofResults from './ProofResults.svelte';
import type { VerifyResponse } from '$lib/api';

const user = userEvent.setup();

function line(overrides: Record<string, unknown> = {}) {
	return {
		valid: true,
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
