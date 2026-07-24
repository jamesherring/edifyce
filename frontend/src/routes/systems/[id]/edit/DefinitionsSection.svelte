<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import BindingsEditor from './BindingsEditor.svelte';
	import RepeatableRows from './RepeatableRows.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { Combobox, type ComboboxOption } from '$lib/components/ui/combobox';
	import { api, type Definition, type Binding } from '$lib/api';
	import { createSectionController } from './section.svelte';

	let {
		systemId,
		definitions,
		sortNames,
		onChanged
	}: {
		systemId: string;
		definitions: Definition[];
		sortNames: string[];
		onChanged: () => Promise<void> | void;
	} = $props();

	// Provisos are plain strings in the API; wrap each in a row so it has a stable
	// identity to key on (bare strings aren't unique and change as you type) —
	// mirroring how RulesSection handles a rule's side-conditions.
	type StringRow = { value: string };

	let sortName = $state('');
	let name = $state('');
	let label = $state('');
	let higher = $state('');
	let lower = $state('');
	let provisos = $state<StringRow[]>([]);
	let bindings = $state<Binding[]>([]);
	let fresh = $state<Binding[]>([]);
	let layerPick = $state<string | null>(null);
	const canSave = $derived(
		!!sortName && name.trim().length > 0 && higher.trim().length > 0 && lower.trim().length > 0
	);

	const s = createSectionController<Definition, ReturnType<typeof payload>>({
		crud: api.parts.definitions,
		systemId: () => systemId,
		noun: 'Definition',
		onChanged: () => onChanged(),
		canSave: () => canSave,
		fill: (item) => {
			sortName = item ? item.sort : (sortNames[0] ?? '');
			name = item?.name ?? '';
			label = item?.label ?? '';
			higher = item?.higher ?? '';
			lower = item?.lower ?? '';
			provisos = item?.provisos.map((v) => ({ value: v })) ?? [];
			bindings = item?.bindings.map((b) => ({ ...b })) ?? [];
			fresh = item?.fresh.map((b) => ({ ...b })) ?? [];
			layerPick = null;
		},
		payload
	});

	function payload() {
		return {
			sort: sortName,
			name: name.trim(),
			// Empty clears the citation label (null): the definition is then reachable
			// only via the generic [Def, line] keyword, not a named citation.
			label: label.trim() || null,
			higher: higher.trim(),
			lower: lower.trim(),
			provisos: provisos.map((p) => p.value.trim()).filter(Boolean),
			bindings: bindings.filter((b) => b.var.trim() && b.sort.trim()),
			fresh: fresh.filter((b) => b.var.trim() && b.sort.trim())
		};
	}

	// Layering: a definition may expand into notation introduced by an *earlier*
	// definition (the engine layers definitions by position). Offer those earlier
	// definitions' notation so the expansion can visibly build on them — all of
	// them for a new definition, only the ones before it when editing.
	const earlierDefinitions = $derived.by(() => {
		const editingId = s.editing?.id;
		if (!editingId) return definitions;
		const index = definitions.findIndex((d) => d.id === editingId);
		return index < 0 ? definitions : definitions.slice(0, index);
	});
	const layerOptions = $derived<ComboboxOption[]>(
		earlierDefinitions.map((d) => ({ value: d.id, label: d.higher, hint: d.name, keywords: d.name }))
	);

	function insertNotation(id: string) {
		const d = definitions.find((x) => x.id === id);
		if (!d) return;
		// Append the chosen notation to the expansion (with a separating space), so
		// selecting a lemma-like definition drops its notation in without clobbering
		// what's already typed.
		lower = lower.trim() ? `${lower.trimEnd()} ${d.higher}` : d.higher;
		layerPick = null;
	}
</script>

<PartSection
	title="Definitions"
	addLabel="Add definition"
	canAdd={sortNames.length > 0}
	items={definitions}
	emptyMessage={sortNames.length === 0
		? 'Add a sort first, then define abbreviations over it.'
		: 'No definitions yet.'}
	onAdd={s.openNew}
	onEdit={s.openEdit}
	onReorder={s.reorder}
	busy={s.busy}
>
	{#snippet row(d)}
		<div class="min-w-0 text-sm">
			<span class="font-medium">{d.name}</span>
			<span class="ml-2 font-mono text-xs">{d.higher}</span>
			<span class="text-muted-foreground"> ≝ </span>
			<span class="font-mono text-xs">{d.lower}</span>
		</div>
	{/snippet}
</PartSection>

<EditSheet
	open={s.open}
	onOpenChange={(o) => (s.open = o)}
	title={s.editing ? 'Edit definition' : 'Add definition'}
	onSave={s.save}
	onDelete={s.editing ? s.del : undefined}
	saving={s.saving}
	{canSave}
>
	<div class="space-y-2">
		<Label for="def-sort">Sort</Label>
		<select
			id="def-sort"
			bind:value={sortName}
			class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
		>
			{#each sortNames as sort (sort)}
				<option value={sort}>{sort}</option>
			{/each}
		</select>
	</div>
	<FormField label="Name" id="def-name" bind:value={name} placeholder="e.g. subset" maxlength={128} />
	<div class="space-y-2">
		<Label for="def-label">Citation label <span class="text-xs text-muted-foreground">(optional)</span></Label>
		<Input id="def-label" bind:value={label} class="font-mono" placeholder="e.g. df-subset" maxlength={64} />
		<p class="text-xs text-muted-foreground">
			Cited in a proof as [label, line]. Must be unique in the system; leave blank to cite only via [Def, line].
		</p>
	</div>
	<div class="space-y-2">
		<Label for="def-higher">Defined form</Label>
		<Input id="def-higher" bind:value={higher} class="font-mono" placeholder="e.g. x ⊆ y" maxlength={512} />
	</div>
	<div class="space-y-2">
		<Label for="def-lower">Expansion</Label>
		<Input id="def-lower" bind:value={lower} class="font-mono" placeholder="e.g. (x = y → x = y)" maxlength={512} />
		{#if layerOptions.length > 0}
			<div class="space-y-1">
				<Label class="text-xs text-muted-foreground">Build on an earlier definition</Label>
				<Combobox
					options={layerOptions}
					bind:value={layerPick}
					onSelect={insertNotation}
					placeholder="Insert defined notation…"
					searchPlaceholder="Search definitions…"
					emptyText="No earlier definitions."
					class="text-muted-foreground"
				/>
			</div>
		{/if}
	</div>
	<BindingsEditor bind:bindings />
	<BindingsEditor
		bind:bindings={fresh}
		label="Bound variables"
		hint="(fresh)"
		description="Variables the expansion binds (e.g. the z in ∀z …). Declaring them lets a quantified definition and its provisos be checked capture-avoidingly."
		addLabel="Add bound variable"
		removeLabel="Remove bound variable"
	/>
	<RepeatableRows
		bind:items={provisos}
		label="Provisos"
		hint="(optional)"
		description="All lines must hold; within a line, combine predicates with 'or'."
		addLabel="Add proviso"
		removeLabel="Remove proviso"
		blank={() => ({ value: '' })}
	>
		{#snippet row(proviso)}
			<Input bind:value={proviso.value} class="font-mono" placeholder="e.g. disjoint(x, y)" maxlength={512} />
		{/snippet}
	</RepeatableRows>
</EditSheet>
