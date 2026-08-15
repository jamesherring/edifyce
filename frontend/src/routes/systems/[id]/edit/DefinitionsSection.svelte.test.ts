import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { api } from '$lib/api';
import type { Definition, SystemValidation } from '$lib/api';
import DefinitionsSection from './DefinitionsSection.svelte';

// The section only side-effects through the api client and toasts; mock both and
// assert on the payload the save sends.
vi.mock('$lib/api', () => ({
	api: {
		parts: {
			definitions: {
				create: vi.fn().mockResolvedValue({}),
				update: vi.fn().mockResolvedValue({}),
				remove: vi.fn().mockResolvedValue(undefined),
				reorder: vi.fn().mockResolvedValue(undefined)
			}
		}
	},
	ApiError: class ApiError extends Error {}
}));
vi.mock('$lib/toast', () => ({ toastSuccess: vi.fn(), toastError: vi.fn() }));

function defn(over: Partial<Definition> = {}): Definition {
	return {
		id: 'd1',
		sort: 'formula',
		name: 'subset',
		higher: 'x sub y',
		lower: 'all z (z in x -> z in y)',
		provisos: ['disjoint(x, y)'],
		bindings: [
			{ var: 'x', sort: 'variable' },
			{ var: 'y', sort: 'variable' }
		],
		fresh: [],
		label: null,
		justification: null,
		...over
	};
}

function renderSection(definitions: Definition[]) {
	const onChanged = vi.fn();
	render(DefinitionsSection, { systemId: 'sys1', definitions, sortNames: ['formula'], symbols: [], onChanged });
	return { onChanged };
}

describe('DefinitionsSection fresh (bound variables)', () => {
	it('pre-fills the fresh editor and sends it in the payload', async () => {
		renderSection([defn({ fresh: [{ var: 'z', sort: 'variable' }] })]);
		await userEvent.click(screen.getByRole('button', { name: /^Edit / }));

		// The stored bound variable is shown.
		expect(screen.getByDisplayValue('z')).toBeInTheDocument();

		// Add a second bound variable, then save.
		await userEvent.click(screen.getByRole('button', { name: 'Add bound variable' }));
		const varInputs = screen.getAllByPlaceholderText('var');
		const sortInputs = screen.getAllByPlaceholderText('sort');
		await userEvent.type(varInputs[varInputs.length - 1], 'w');
		await userEvent.type(sortInputs[sortInputs.length - 1], 'variable');

		await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

		const [, , payload] = vi.mocked(api.parts.definitions.update).mock.calls[0];
		expect(payload).toMatchObject({
			fresh: [
				{ var: 'z', sort: 'variable' },
				{ var: 'w', sort: 'variable' }
			]
		});
	});
});

describe('DefinitionsSection label (citation name)', () => {
	it('pre-fills the label and sends the edited value in the payload', async () => {
		renderSection([defn({ label: 'df-subset' })]);
		await userEvent.click(screen.getByRole('button', { name: /^Edit / }));

		const input = screen.getByDisplayValue('df-subset');
		await userEvent.clear(input);
		await userEvent.type(input, 'subseteq');
		await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

		const [, , payload] = vi.mocked(api.parts.definitions.update).mock.calls[0];
		expect(payload).toMatchObject({ label: 'subseteq' });
	});

	it('sends null when the label is cleared (unnamed definition)', async () => {
		renderSection([defn({ label: 'df-subset' })]);
		await userEvent.click(screen.getByRole('button', { name: /^Edit / }));

		await userEvent.clear(screen.getByDisplayValue('df-subset'));
		await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

		const [, , payload] = vi.mocked(api.parts.definitions.update).mock.calls[0];
		expect(payload.label).toBeNull();
	});
});

describe('DefinitionsSection provisos', () => {
	it('pre-fills the provisos editor from a definition’s provisos', async () => {
		renderSection([defn()]);
		await userEvent.click(screen.getByRole('button', { name: /^Edit / }));
		expect(screen.getByDisplayValue('disjoint(x, y)')).toBeInTheDocument();
	});

	it('sends edited provisos, trimmed and blank-filtered', async () => {
		renderSection([defn()]);
		await userEvent.click(screen.getByRole('button', { name: /^Edit / }));

		// Add a second proviso and a blank one; the blank must be dropped.
		await userEvent.click(screen.getByRole('button', { name: 'Add proviso' }));
		await userEvent.click(screen.getByRole('button', { name: 'Add proviso' }));
		const inputs = screen.getAllByPlaceholderText('e.g. disjoint(x, y)');
		await userEvent.type(inputs[1], '  not occurs(x, y)  ');
		// inputs[2] left blank

		await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

		const [, , payload] = vi.mocked(api.parts.definitions.update).mock.calls[0];
		expect(payload).toMatchObject({ provisos: ['disjoint(x, y)', 'not occurs(x, y)'] });
	});
});

// Open the layering picker. The native Sort <select> also carries the `combobox`
// role, so this relies on the picker's accessible name to tell them apart —
// which is exactly what a screen-reader or voice-control user has to do.
async function openLayerPicker() {
	await userEvent.click(screen.getByRole('combobox', { name: 'Build on an earlier definition' }));
}

// The picker's own options, by our command-item slot — the notation also shows
// in the definition list rows and the Sort <select>'s <option>s, so a bare role
// query would be ambiguous.
function pickerOptionTexts(): string[] {
	return Array.from(document.querySelectorAll('[data-slot="command-item"]')).map(
		(el) => el.textContent ?? ''
	);
}

describe('DefinitionsSection layering', () => {
	it('names the layering picker, which a combobox cannot take from its contents', async () => {
		const earlier = defn({ id: 'd0', name: 'member', higher: 'x in y' });
		const later = defn({ id: 'd1', name: 'subset', higher: 'x sub y' });
		renderSection([earlier, later]);
		await userEvent.click(screen.getAllByRole('button', { name: /^Edit / })[1]);

		// role="combobox" takes no name from its contents, so without an explicit
		// one this control reached assistive tech unnamed.
		expect(
			screen.getByRole('combobox', { name: 'Build on an earlier definition' })
		).toBeInTheDocument();
	});

	it('inserts an earlier definition’s notation into the expansion', async () => {
		const earlier = defn({ id: 'd0', name: 'member', higher: 'x in y', lower: '…', provisos: [] });
		const later = defn({ id: 'd1', name: 'subset', higher: 'x sub y', lower: '', provisos: [] });
		renderSection([earlier, later]);

		// Edit the *second* definition — only the earlier one is offered to build on.
		await userEvent.click(screen.getAllByRole('button', { name: /^Edit / })[1]);
		await openLayerPicker();
		const option = await waitFor(() => {
			const el = document.querySelector<HTMLElement>('[data-slot="command-item"]');
			if (!el) throw new Error('option not yet rendered');
			return el;
		});
		await userEvent.click(option);

		// Its notation is appended to the (empty) expansion input.
		expect(screen.getByDisplayValue('x in y')).toBeInTheDocument();
	});

	it('appends to a non-empty expansion without clobbering it', async () => {
		const earlier = defn({ id: 'd0', name: 'member', higher: 'x in y', lower: '…', provisos: [] });
		const later = defn({ id: 'd1', name: 'subset', higher: 'x sub y', lower: '(a ->', provisos: [] });
		renderSection([earlier, later]);

		await userEvent.click(screen.getAllByRole('button', { name: /^Edit / })[1]);
		await openLayerPicker();
		const option = await waitFor(() => {
			const el = document.querySelector<HTMLElement>('[data-slot="command-item"]');
			if (!el) throw new Error('option not yet rendered');
			return el;
		});
		await userEvent.click(option);

		// Appended after the existing text with a separating space.
		expect(screen.getByDisplayValue('(a -> x in y')).toBeInTheDocument();
	});

	it('offers only *earlier* definitions when editing a middle one', async () => {
		// The picker's whole purpose is positional layering: editing d1 (index 1)
		// must offer d0 and neither itself (d1) nor the later d2.
		const defs = [
			defn({ id: 'd0', name: 'member', higher: 'mem', lower: 'a', provisos: [] }),
			defn({ id: 'd1', name: 'subset', higher: 'sub', lower: 'b', provisos: [] }),
			defn({ id: 'd2', name: 'power', higher: 'pow', lower: 'c', provisos: [] })
		];
		renderSection(defs);

		await userEvent.click(screen.getAllByRole('button', { name: /^Edit / })[1]);
		await openLayerPicker();
		await waitFor(() => expect(pickerOptionTexts().length).toBeGreaterThan(0));

		const texts = pickerOptionTexts();
		expect(texts).toHaveLength(1);
		expect(texts[0]).toContain('mem'); // d0, the only earlier definition
		expect(texts.join(' ')).not.toContain('pow'); // d2 (later) is excluded
		expect(texts.join(' ')).not.toContain('sub'); // d1 (self) is excluded
	});

	it('offers nothing to build on for the first definition', async () => {
		renderSection([defn({ id: 'd0', lower: 'first' })]);
		await userEvent.click(screen.getByRole('button', { name: /^Edit / }));
		// The layering picker (label + combobox) only renders when an earlier
		// definition exists.
		expect(screen.queryByText('Build on an earlier definition')).not.toBeInTheDocument();
	});
});

// A `fresh` clause need not be written: a grammar declaring binding slots has one
// inferred from the parsed defining form. Inference is silent at build, so the
// build's report is where the author sees what it concluded.
describe('DefinitionsSection build report', () => {
	function validation(over: Partial<SystemValidation> = {}): SystemValidation {
		return {
			success: true,
			errors: [],
			system_name: 'S',
			line_type_count: 1,
			inference_rule_count: 0,
			definitions: [],
			...over
		};
	}

	function renderWith(v: SystemValidation | null, validating = false) {
		render(DefinitionsSection, {
			systemId: 'sys1',
			definitions: [defn()],
			sortNames: ['formula'],
			symbols: [],
			onChanged: vi.fn(),
			validation: v,
			validating
		});
	}

	it('reports a binder the engine read off the grammar', async () => {
		renderWith(
			validation({
				definitions: [
					{
						definition_id: 'd1',
						label: null,
						defined_form: 'x sub y',
						binders: [{ var: 'z', sort: 'variable', inferred: true }]
					}
				]
			})
		);
		await userEvent.click(screen.getByRole('button', { name: /^Edit / }));

		expect(await screen.findByText(/inferred from the grammar/)).toBeInTheDocument();
		expect(screen.getByText('z : variable')).toBeInTheDocument();
	});

	it('distinguishes a binder the author declared', async () => {
		renderWith(
			validation({
				definitions: [
					{
						definition_id: 'd1',
						label: null,
						defined_form: 'x sub y',
						binders: [{ var: 'z', sort: 'variable', inferred: false }]
					}
				]
			})
		);
		await userEvent.click(screen.getByRole('button', { name: /^Edit / }));

		expect(await screen.findByText(/as declared/)).toBeInTheDocument();
	});

	it('says so when the definition was dropped at build', async () => {
		// A definition absent from a *successful* build's report did not layer: its
		// expansion matched nothing, so it is silently not there. That silence is
		// exactly what the report is for.
		renderWith(validation({ definitions: [] }));
		await userEvent.click(screen.getByRole('button', { name: /^Edit / }));

		expect(await screen.findByText(/dropped/)).toBeInTheDocument();
	});

	it('reports nothing from a build that failed', async () => {
		// The report is empty on a failed build, so absence proves nothing — saying
		// "dropped" for every definition at once would be worse than staying quiet.
		renderWith(validation({ success: false, errors: ['nope'], definitions: [] }));
		await userEvent.click(screen.getByRole('button', { name: /^Edit / }));
		await screen.findByRole('button', { name: /Save changes/ });

		expect(screen.queryByText(/dropped/)).toBeNull();
		expect(screen.queryByText(/settled on/)).toBeNull();
	});

	it('reports nothing while a fresh build is in flight', async () => {
		// A definition saved a moment ago is in the refreshed list before the build
		// that would mention it has run. A report from the build *before* it does
		// not have the definition — which looks exactly like a dropped one, and
		// would say so with the same confidence.
		renderWith(validation({ definitions: [] }), true);
		await userEvent.click(screen.getByRole('button', { name: /^Edit / }));
		await screen.findByRole('button', { name: /Save changes/ });

		expect(screen.queryByText(/dropped/)).toBeNull();
		expect(screen.queryByText(/settled on/)).toBeNull();
	});
});
