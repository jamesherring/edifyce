<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import { api, type Sort } from '$lib/api';
	import { createSectionController } from './section.svelte';

	let {
		systemId,
		sorts,
		onChanged
	}: {
		systemId: string;
		sorts: Sort[];
		onChanged: () => Promise<void> | void;
	} = $props();

	let name = $state('');
	const canSave = $derived(name.trim().length > 0);

	const s = createSectionController<Sort, { name: string }>({
		crud: api.parts.sorts,
		systemId: () => systemId,
		noun: 'Sort',
		onChanged: () => onChanged(),
		canSave: () => canSave,
		fill: (item) => (name = item?.name ?? ''),
		payload: () => ({ name: name.trim() })
	});
</script>

<PartSection
	title="Sorts"
	id="sorts"
	addLabel="Add sort"
	items={sorts}
	emptyMessage="No sorts yet — a sort is a syntactic category like “term” or “formula”."
	onAdd={s.openNew}
	onEdit={s.openEdit}
	onReorder={s.reorder}
	busy={s.busy}
>
	{#snippet row(sort)}
		<span class="font-mono text-sm">{sort.name}</span>
	{/snippet}
</PartSection>

<EditSheet
	open={s.open}
	onOpenChange={(o) => (s.open = o)}
	title={s.editing ? 'Edit sort' : 'Add sort'}
	onSave={s.save}
	onDelete={s.editing ? s.del : undefined}
	saving={s.saving}
	{canSave}
>
	<FormField label="Name" id="sort-name" bind:value={name} placeholder="e.g. term" maxlength={128} />
</EditSheet>
