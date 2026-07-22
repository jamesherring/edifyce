<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import BindingsEditor from './BindingsEditor.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
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

	let sortName = $state('');
	let name = $state('');
	let higher = $state('');
	let lower = $state('');
	let condition = $state('');
	let bindings = $state<Binding[]>([]);
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
			higher = item?.higher ?? '';
			lower = item?.lower ?? '';
			condition = item?.condition ?? '';
			bindings = item?.bindings.map((b) => ({ ...b })) ?? [];
		},
		payload
	});

	function payload() {
		return {
			sort: sortName,
			name: name.trim(),
			higher: higher.trim(),
			lower: lower.trim(),
			condition: condition.trim() || null,
			bindings: bindings.filter((b) => b.var.trim() && b.sort.trim())
		};
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
		<Label for="def-higher">Defined form</Label>
		<Input id="def-higher" bind:value={higher} class="font-mono" placeholder="e.g. x ⊆ y" maxlength={512} />
	</div>
	<div class="space-y-2">
		<Label for="def-lower">Expansion</Label>
		<Input id="def-lower" bind:value={lower} class="font-mono" placeholder="e.g. (x = y → x = y)" maxlength={512} />
	</div>
	<div class="space-y-2">
		<Label for="def-condition">Condition <span class="text-muted-foreground">(optional)</span></Label>
		<Input id="def-condition" bind:value={condition} class="font-mono" maxlength={512} />
	</div>
	<BindingsEditor bind:bindings />
</EditSheet>
