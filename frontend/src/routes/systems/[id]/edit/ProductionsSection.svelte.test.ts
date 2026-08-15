import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import ProductionsSection from './ProductionsSection.svelte';

vi.mock('$lib/api', () => ({
	api: {
		parts: { productions: { create: vi.fn(), update: vi.fn(), remove: vi.fn(), reorder: vi.fn() } }
	},
	ApiError: class ApiError extends Error {}
}));
vi.mock('$lib/toast', () => ({ toastSuccess: vi.fn(), toastError: vi.fn() }));

const user = userEvent.setup({ pointerEventsCheck: 0 });
afterEach(() => {
	vi.clearAllMocks();
	document.body.style.pointerEvents = '';
});

function prod(sort: string) {
	return {
		id: 'p1',
		name: 'membership',
		sort,
		kind: 'composite',
		template: 's ∈ t',
		regex: null,
		atom_value: null,
		atom_base: null,
		denotes_constant: false,
		bindings: []
	};
}

// The P1 fix: a production's stored sort may have been deleted since, leaving the
// <select> blank on a stale value. canSave must validate it against the live
// sort names so an invalid value can't be submitted.
describe('ProductionsSection sort validation', () => {
	it('disables Save when the stored sort is no longer a known sort', async () => {
		render(ProductionsSection, {
			systemId: 'sys-1',
			productions: [prod('ghost')], // 'ghost' was deleted
			sortNames: ['term', 'formula'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		const save = await screen.findByRole('button', { name: /Save changes/ });

		// Name + template are filled from the production, so only the stale sort
		// keeps Save disabled.
		expect(save).toBeDisabled();

		// Picking a real sort clears it.
		await user.selectOptions(screen.getByLabelText('Sort'), 'formula');
		expect(save).toBeEnabled();
	});

	it('enables Save when the stored sort is still valid', async () => {
		render(ProductionsSection, {
			systemId: 'sys-1',
			productions: [prod('formula')],
			sortNames: ['term', 'formula'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		const save = await screen.findByRole('button', { name: /Save changes/ });
		expect(save).toBeEnabled();
	});
});

function atomFamily() {
	return {
		id: 'p2',
		name: 'prop',
		sort: 'formula',
		kind: 'atom',
		template: null,
		regex: null,
		atom_value: null,
		atom_base: 'p',
		denotes_constant: false,
		bindings: []
	};
}

describe('ProductionsSection atom productions', () => {
	it('opens an atom family in Family mode showing its base', async () => {
		render(ProductionsSection, {
			systemId: 'sys-1',
			productions: [atomFamily()],
			sortNames: ['formula'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		await screen.findByRole('button', { name: /Save changes/ });
		// fill() picked the atom_base discriminator, so the value input holds the base.
		expect(screen.getByDisplayValue('p')).toBeTruthy();
	});
});

describe('ProductionsSection object-language role', () => {
	it('shows a leaf as variable-like by default and toggles it to constant', async () => {
		render(ProductionsSection, {
			systemId: 'sys-1',
			productions: [atomConstant()],
			sortNames: ['formula'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		const toggle = await screen.findByRole('button', { name: /object language/i });

		// Off by default: an undeclared leaf is read as a variable, which refuses a
		// definition that introduces it rather than letting one capture it.
		expect(toggle.getAttribute('aria-pressed')).toBe('false');
		await user.click(toggle);
		expect(toggle.getAttribute('aria-pressed')).toBe('true');
	});

	it('reflects a production already declared constant', async () => {
		render(ProductionsSection, {
			systemId: 'sys-1',
			productions: [{ ...atomConstant(), denotes_constant: true }],
			sortNames: ['formula'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		const toggle = await screen.findByRole('button', { name: /object language/i });
		expect(toggle.getAttribute('aria-pressed')).toBe('true');
	});

	it('hides the toggle for an indexed family, which can never be a constant', async () => {
		render(ProductionsSection, {
			systemId: 'sys-1',
			productions: [atomFamily()],
			sortNames: ['formula'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		await screen.findByRole('button', { name: /Save changes/ });
		expect(screen.queryByRole('button', { name: /object language/i })).toBeNull();
	});

	it('hides the toggle for a composite with slots, which is never a leaf', async () => {
		render(ProductionsSection, {
			systemId: 'sys-1',
			productions: [{ ...prod('formula'), bindings: [{ var: 's', sort: 'term' }] }],
			sortNames: ['formula', 'term'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		await screen.findByRole('button', { name: /Save changes/ });
		expect(screen.queryByRole('button', { name: /object language/i })).toBeNull();
	});
});

function atomConstant() {
	return {
		id: 'p3',
		name: 'falsum',
		sort: 'formula',
		kind: 'atom',
		template: null,
		regex: null,
		atom_value: '⊥',
		atom_base: null,
		denotes_constant: false,
		bindings: []
	};
}

// A slot's `scopes_over` names its siblings, and the editor refers to them by an
// editor-local id rather than by name — so a rename carries the declaration with
// it, and a target that no longer exists is unrepresentable rather than a 400 the
// user has no way to repair from this form.
describe('ProductionsSection binding slots', () => {
	function binder() {
		return {
			...prod('formula'),
			name: 'forall',
			template: '∀x.phi',
			bindings: [
				{ var: 'x', sort: 'setvar', scopes_over: ['phi'] },
				{ var: 'phi', sort: 'formula' }
			]
		};
	}

	it('sends an untouched binding slot back unchanged', async () => {
		render(ProductionsSection, {
			systemId: 'sys-1',
			productions: [binder()],
			sortNames: ['formula', 'setvar'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		await user.click(await screen.findByRole('button', { name: /Save changes/ }));

		const { api } = await import('$lib/api');
		expect(vi.mocked(api.parts.productions.update).mock.calls[0][2].bindings).toEqual([
			{ var: 'x', sort: 'setvar', scopes_over: ['phi'] },
			{ var: 'phi', sort: 'formula', scopes_over: [] }
		]);
	});

	it('follows a scope target through a rename', async () => {
		render(ProductionsSection, {
			systemId: 'sys-1',
			productions: [binder()],
			sortNames: ['formula', 'setvar'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		const slot = await screen.findByDisplayValue('phi');
		await user.clear(slot);
		await user.type(slot, 'psi');
		await user.click(screen.getByRole('button', { name: /Save changes/ }));

		const { api } = await import('$lib/api');
		expect(vi.mocked(api.parts.productions.update).mock.calls[0][2].bindings).toEqual([
			{ var: 'x', sort: 'setvar', scopes_over: ['psi'] },
			{ var: 'psi', sort: 'formula', scopes_over: [] }
		]);
	});

	it('drops a scope target whose slot was removed', async () => {
		render(ProductionsSection, {
			systemId: 'sys-1',
			productions: [binder()],
			sortNames: ['formula', 'setvar'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		const remove = await screen.findAllByRole('button', { name: /Remove slot/ });
		await user.click(remove[1]);
		await user.click(screen.getByRole('button', { name: /Save changes/ }));

		const { api } = await import('$lib/api');
		expect(vi.mocked(api.parts.productions.update).mock.calls[0][2].bindings).toEqual([
			{ var: 'x', sort: 'setvar', scopes_over: [] }
		]);
	});

	it('toggles a scope target off and back on', async () => {
		render(ProductionsSection, {
			systemId: 'sys-1',
			productions: [binder()],
			sortNames: ['formula', 'setvar'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));

		// One button per sibling slot: `x` offers `phi`, and `phi` offers `x`.
		const [xBindsPhi, phiBindsX] = await screen.findAllByRole('button', { name: /binds over/ });
		expect(xBindsPhi.getAttribute('aria-pressed')).toBe('true');
		expect(phiBindsX.getAttribute('aria-pressed')).toBe('false');

		await user.click(xBindsPhi);
		expect(xBindsPhi.getAttribute('aria-pressed')).toBe('false');
		await user.click(phiBindsX);
		await user.click(screen.getByRole('button', { name: /Save changes/ }));

		const { api } = await import('$lib/api');
		expect(vi.mocked(api.parts.productions.update).mock.calls[0][2].bindings).toEqual([
			{ var: 'x', sort: 'setvar', scopes_over: [] },
			{ var: 'phi', sort: 'formula', scopes_over: ['x'] }
		]);
	});

	it('offers no target for a production with one slot', async () => {
		render(ProductionsSection, {
			systemId: 'sys-1',
			productions: [
				{ ...prod('formula'), bindings: [{ var: 's', sort: 'term', scopes_over: [] }] }
			],
			sortNames: ['formula', 'term'],
			symbols: [],
			onChanged: vi.fn()
		});
		await user.click(screen.getByRole('button', { name: /^Edit / }));
		await screen.findByRole('button', { name: /Save changes/ });
		expect(screen.queryByRole('button', { name: /binds over/ })).toBeNull();
	});
});
