<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import BindingsEditor from './BindingsEditor.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { Button } from '$lib/components/ui/button';
	import { api, type Production, type ProductionBinding } from '$lib/api';
	import type { SymbolEntry } from '$lib/symbols';
	import type { NotationGroup } from '$lib/notation';
	import { createSectionController } from './section.svelte';

	let {
		systemId,
		productions,
		sortNames,
		symbols,
		onChanged,
		notation = []
	}: {
		systemId: string;
		productions: Production[];
		sortNames: string[];
		symbols: SymbolEntry[];
		onChanged: () => Promise<void> | void;
		/** Optional: the grammar reference shown in the edit sheet. */
		notation?: NotationGroup[];
	} = $props();

	type Mode = 'template' | 'regex' | 'atom_value' | 'atom_base';
	const MODES: { key: Mode; label: string; placeholder: string }[] = [
		{ key: 'template', label: 'Template', placeholder: 'e.g. (p → q)' },
		{ key: 'regex', label: 'Regex', placeholder: 'e.g. [a-z][a-z0-9]*' },
		{ key: 'atom_value', label: 'Atom', placeholder: 'a constant token, e.g. ⊥' },
		{ key: 'atom_base', label: 'Family', placeholder: 'a base, e.g. p (the p_# family)' }
	];

	let name = $state('');
	let sortName = $state('');
	let mode = $state<Mode>('template');
	let value = $state('');
	let denotesConstant = $state(false);
	let bindings = $state<ProductionBinding[]>([]);

	// A composite with slots is never a leaf, so the question cannot arise for it;
	// a nullary template (`S`, `∅`) *is* a leaf, so it keeps the toggle. An indexed
	// family is a supply of interchangeable tokens and can never be a constant —
	// the engine refuses that declaration outright, so don't offer it.
	const canDeclareConstant = $derived(
		mode !== 'atom_base' && (mode !== 'template' || bindings.length === 0)
	);

	const placeholder = $derived(MODES.find((m) => m.key === mode)!.placeholder);

	// `sortName` must resolve to a real sort: a production's stored sort may have
	// been deleted since, leaving the <select> blank on a stale value — block
	// saving that rather than POSTing an invalid sort for a backend 4xx.
	const canSave = $derived(
		name.trim().length > 0 && sortNames.includes(sortName) && value.trim().length > 0
	);

	const s = createSectionController<Production, ReturnType<typeof payload>>({
		crud: api.parts.productions,
		systemId: () => systemId,
		noun: 'Production',
		onChanged: () => onChanged(),
		canSave: () => canSave,
		fill: (item) => {
			name = item?.name ?? '';
			sortName = item ? item.sort : (sortNames[0] ?? '');
			mode = !item
				? 'template'
				: item.regex !== null
					? 'regex'
					: item.atom_value !== null
						? 'atom_value'
						: item.atom_base !== null
							? 'atom_base'
							: 'template';
			value = item
				? (item.template ?? item.regex ?? item.atom_value ?? item.atom_base ?? '')
				: '';
			denotesConstant = item?.denotes_constant ?? false;
			bindings = item?.bindings.map((b) => ({ ...b })) ?? [];
		},
		payload
	});

	function payload() {
		// Send all four discriminator fields with the inactive ones nulled so a
		// mode switch clears the others; the backend requires exactly one set.
		// Bindings only apply to a composite template.
		const v = value.trim();
		const slots = mode === 'template' ? bindings.filter((b) => b.var.trim() && b.sort.trim()) : [];
		const slotNames = new Set(slots.map((b) => b.var.trim()));
		return {
			name: name.trim(),
			sort: sortName,
			template: mode === 'template' ? v : null,
			regex: mode === 'regex' ? v : null,
			atom_value: mode === 'atom_value' ? v : null,
			atom_base: mode === 'atom_base' ? v : null,
			// Sent as-is for a composite with slots, where the flag is inert (it is
			// only ever read of a ground leaf) — the editor hides the toggle rather
			// than forcing a value, so the setting survives if the slots go. Forced
			// off for a family, where it is not inert but a build error, so switching
			// a declared constant to Family mode can't store an unbuildable row.
			denotes_constant: mode === 'atom_base' ? false : denotesConstant,
			// A binder's `scopes_over` names sibling slots, and there is no control
			// here to edit it (see docs/binding-slots-design.md) — so it rides along
			// untouched, and renaming or removing the slot it names would send a
			// target that no longer exists. The backend rejects that, which would
			// dead-end an edit the user has no way to repair. Drop the stale target
			// instead: a scope over a slot that is gone is not a declaration worth
			// keeping.
			bindings: slots.map((b) => ({
				...b,
				scopes_over: (b.scopes_over ?? []).filter(
					(target) => slotNames.has(target) && target !== b.var.trim()
				)
			}))
		};
	}
</script>

<PartSection
	title="Grammar"
	itemLabel={(p) => `production ${p.name}`}
	id="grammar"
	addLabel="Add production"
	canAdd={sortNames.length > 0}
	items={productions}
	emptyMessage={sortNames.length === 0
		? 'Add a sort first, then define its productions.'
		: 'No productions yet — these define the concrete syntax of each sort.'}
	onAdd={s.openNew}
	onEdit={s.openEdit}
	onReorder={s.reorder}
	busy={s.busy}
>
	{#snippet row(p)}
		<div class="min-w-0 text-sm">
			<span class="font-medium">{p.name}</span>
			<span class="text-muted-foreground"> : {p.sort}</span>
			<span class="ml-2 font-mono text-xs text-muted-foreground">
				{p.template ??
					p.atom_value ??
					(p.atom_base !== null ? `${p.atom_base}_#` : `matches ${p.regex}`)}
			</span>
		</div>
	{/snippet}
</PartSection>

<EditSheet
	open={s.open}
	onOpenChange={(o) => (s.open = o)}
	title={s.editing ? 'Edit production' : 'Add production'}
	onSave={s.save}
	onDelete={s.editing ? s.del : undefined}
	saving={s.saving}
	{canSave}
	{notation}
	{symbols}
>
	<FormField label="Name" id="prod-name" bind:value={name} placeholder="e.g. implication" maxlength={128} />
	<div class="space-y-2">
		<Label for="prod-sort">Sort</Label>
		<select
			id="prod-sort"
			bind:value={sortName}
			class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
		>
			{#each sortNames as sort (sort)}
				<option value={sort}>{sort}</option>
			{/each}
		</select>
	</div>
	<div class="space-y-2">
		<Label>Rule</Label>
		<div class="inline-flex flex-wrap rounded-md border p-0.5 text-sm">
			{#each MODES as m (m.key)}
				<button
					type="button"
					aria-pressed={mode === m.key}
					onclick={() => (mode = m.key)}
					class={[
						'rounded px-3 py-1',
						mode === m.key ? 'bg-accent text-accent-foreground' : 'text-muted-foreground'
					]}
				>
					{m.label}
				</button>
			{/each}
		</div>
		<Input bind:value class="font-mono" data-symbol-field {placeholder} maxlength={512} />
	</div>
	{#if mode === 'template'}
		<BindingsEditor bind:bindings />
	{/if}
	{#if canDeclareConstant}
		<div class="space-y-2">
			<div class="flex items-center justify-between">
				<Label>Constant of the object language</Label>
				<Button
					type="button"
					size="sm"
					aria-pressed={denotesConstant}
					variant={denotesConstant ? 'default' : 'outline'}
					onclick={() => (denotesConstant = !denotesConstant)}
				>
					<!-- Prefix rather than aria-label: an aria-label would replace the
					     visible word, leaving "Off" unspeakable to voice control. -->
					<span class="sr-only">Constant of the object language:</span>
					{denotesConstant ? 'Constant' : 'Variable'}
				</Button>
			</div>
			<p class="text-xs text-muted-foreground">
				Whether these tokens name one fixed thing (<span class="font-mono">⊥</span>,
				<span class="font-mono">∅</span>) or stand for variables a quantifier can
				bind. Nothing about the production's shape decides this — a single token is
				a constant in <span class="font-mono">formula ::= ⊥</span> and a variable in
				<span class="font-mono">setvar ::= a | b | c</span>. Only a constant may
				appear in a definition's defining form without the defined form supplying
				it; marking a bindable token constant lets a definition capture it.
			</p>
		</div>
	{/if}
</EditSheet>
