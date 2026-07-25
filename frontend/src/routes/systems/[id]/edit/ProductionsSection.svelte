<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import BindingsEditor from './BindingsEditor.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { api, type Production, type Binding } from '$lib/api';
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
	let bindings = $state<Binding[]>([]);

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
			bindings = item?.bindings.map((b) => ({ ...b })) ?? [];
		},
		payload
	});

	function payload() {
		// Send all four discriminator fields with the inactive ones nulled so a
		// mode switch clears the others; the backend requires exactly one set.
		// Bindings only apply to a composite template.
		const v = value.trim();
		return {
			name: name.trim(),
			sort: sortName,
			template: mode === 'template' ? v : null,
			regex: mode === 'regex' ? v : null,
			atom_value: mode === 'atom_value' ? v : null,
			atom_base: mode === 'atom_base' ? v : null,
			bindings: mode === 'template' ? bindings.filter((b) => b.var.trim() && b.sort.trim()) : []
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
</EditSheet>
