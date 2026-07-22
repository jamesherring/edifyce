<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import RepeatableRows from './RepeatableRows.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { api, type LineType, type LinePartInput } from '$lib/api';
	import { createSectionController } from './section.svelte';

	let {
		systemId,
		lines,
		sortNames,
		onChanged
	}: {
		systemId: string;
		lines: LineType[];
		sortNames: string[];
		onChanged: () => Promise<void> | void;
	} = $props();

	let name = $state('');
	let shape = $state('');
	let logicalSort = $state('');
	let parts = $state<LinePartInput[]>([]);

	// The logical sort is optional (empty = "none"), but a non-empty value must
	// name a real sort: the stored one may have been deleted since, leaving the
	// <select> blank on a stale value. Block saving that rather than PATCHing an
	// invalid logical_sort for a backend 4xx.
	const logicalSortValid = $derived(logicalSort === '' || sortNames.includes(logicalSort));
	const canSave = $derived(
		name.trim().length > 0 && shape.trim().length > 0 && logicalSortValid
	);

	const s = createSectionController<LineType, ReturnType<typeof payload>>({
		crud: api.parts.lineTypes,
		systemId: () => systemId,
		noun: 'Line type',
		onChanged: () => onChanged(),
		canSave: () => canSave,
		fill: (item) => {
			name = item?.name ?? '';
			shape = item?.shape ?? '';
			logicalSort = item?.logical_sort ?? '';
			parts = item?.parts.map((p) => ({ name: p.name, regex: p.regex })) ?? [];
		},
		payload
	});

	function payload() {
		return {
			name: name.trim(),
			shape: shape.trim(),
			logical_sort: logicalSort || null,
			parts: parts
				.filter((p) => p.name.trim() && p.regex.trim())
				.map((p) => ({ name: p.name.trim(), regex: p.regex.trim() }))
		};
	}
</script>

<!-- The backend allows a single line type per system. -->
<PartSection
	title="Line type"
	addLabel="Add line type"
	canAdd={lines.length === 0}
	items={lines}
	emptyMessage="No line type yet — this defines the shape of each proof line."
	onAdd={s.openNew}
	onEdit={s.openEdit}
	onReorder={() => {}}
	busy={s.saving}
>
	{#snippet row(l)}
		<div class="min-w-0 text-sm">
			<span class="font-medium">{l.name}</span>
			<span class="ml-2 font-mono text-xs text-muted-foreground">{l.shape}</span>
		</div>
	{/snippet}
</PartSection>

<EditSheet
	open={s.open}
	onOpenChange={(o) => (s.open = o)}
	title={s.editing ? 'Edit line type' : 'Add line type'}
	onSave={s.save}
	onDelete={s.editing ? s.del : undefined}
	saving={s.saving}
	{canSave}
>
	<FormField label="Name" id="line-name" bind:value={name} placeholder="e.g. statement" maxlength={128} />
	<div class="space-y-2">
		<Label for="line-shape">Shape</Label>
		<Input id="line-shape" bind:value={shape} class="font-mono" placeholder="e.g. <formula> [<reference>]" maxlength={256} />
	</div>
	<div class="space-y-2">
		<Label for="line-logical">Logical sort <span class="text-muted-foreground">(optional)</span></Label>
		<select
			id="line-logical"
			bind:value={logicalSort}
			class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
		>
			<option value="">— none —</option>
			{#each sortNames as sortName (sortName)}
				<option value={sortName}>{sortName}</option>
			{/each}
		</select>
	</div>
	<RepeatableRows
		bind:items={parts}
		label="Parts"
		hint="(named sub-patterns in the shape)"
		addLabel="Add part"
		removeLabel="Remove part"
		blank={() => ({ name: '', regex: '' })}
	>
		{#snippet row(part)}
			<Input bind:value={part.name} class="font-mono" placeholder="name" maxlength={128} />
			<span class="text-muted-foreground">matches</span>
			<Input bind:value={part.regex} class="font-mono" placeholder="regex" maxlength={512} />
		{/snippet}
	</RepeatableRows>
</EditSheet>
