import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import SystemOutline from './SystemOutline.svelte';
import type { SystemValidation } from '$lib/api';

const user = userEvent.setup();

const SECTIONS = [
	{ id: 'sorts', title: 'Sorts', count: 2 },
	{ id: 'grammar', title: 'Grammar', count: 4 },
	{ id: 'rules', title: 'Inference rules', count: 0 }
];

function validation(over: Partial<SystemValidation> = {}): SystemValidation {
	return {
		success: true,
		errors: [],
		system_name: 'Test system',
		line_type_count: 1,
		inference_rule_count: 2,
		...over
	};
}

function setup(over: { validation?: SystemValidation | null; validating?: boolean } = {}) {
	return render(SystemOutline, {
		sections: SECTIONS,
		// `in`, not `??`: an explicit null means "no verdict yet", which is the case
		// the loading state is about.
		validation: 'validation' in over ? (over.validation ?? null) : validation(),
		validating: over.validating ?? false
	});
}

describe('SystemOutline', () => {
	it('links every section, with its item count', () => {
		setup();
		const nav = screen.getByRole('navigation', { name: 'System contents' });
		const links = [...nav.querySelectorAll('a')];
		expect(links.map((a) => a.getAttribute('href'))).toEqual(['#sorts', '#grammar', '#rules']);
		expect(links.map((a) => a.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
			'Sorts 2',
			'Grammar 4',
			// An empty section is still listed — that it has nothing is the point.
			'Inference rules 0'
		]);
	});

	it('pins the clicked section, so a jump that lands short still reads right', async () => {
		setup();
		const sorts = screen.getByRole('link', { name: /Sorts/ });
		await user.click(sorts);
		expect(sorts).toHaveAttribute('aria-current', 'location');
		expect(screen.getByRole('link', { name: /Grammar/ })).not.toHaveAttribute('aria-current');
	});

	it('marks exactly one section as current', async () => {
		setup();
		await user.click(screen.getByRole('link', { name: /Grammar/ }));
		const nav = screen.getByRole('navigation', { name: 'System contents' });
		expect(nav.querySelectorAll('[aria-current="location"]')).toHaveLength(1);
	});

	it('shows the compile verdict beside the outline', () => {
		setup();
		expect(screen.getByText('Compiles cleanly')).toBeInTheDocument();
		expect(screen.getByText('1 line type(s), 2 rule(s).')).toBeInTheDocument();
	});

	it('lists the errors when the system does not compile', () => {
		setup({ validation: validation({ success: false, errors: ['unknown sort: formula'] }) });
		expect(screen.getByText('Does not compile (1)')).toBeInTheDocument();
		expect(screen.getByText('unknown sort: formula')).toBeInTheDocument();
	});

	it('says it is checking before the first verdict arrives', () => {
		setup({ validation: null, validating: true });
		expect(screen.getByText('Checking…')).toBeInTheDocument();
	});
});
