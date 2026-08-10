<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import RepeatableRows from '$lib/components/RepeatableRows.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { Button } from '$lib/components/ui/button';
	import { api, type LineType, type LinePartInput, type LineScope } from '$lib/api';
	import type { SymbolEntry } from '$lib/symbols';
	import type { NotationGroup } from '$lib/notation';
	import { createSectionController } from './section.svelte';

	let {
		systemId,
		lines,
		sortNames,
		symbols,
		onChanged,
		notation = []
	}: {
		systemId: string;
		lines: LineType[];
		sortNames: string[];
		symbols: SymbolEntry[];
		onChanged: () => Promise<void> | void;
		/** Optional: the grammar reference shown in the edit sheet. */
		notation?: NotationGroup[];
	} = $props();

	let name = $state('');
	let shape = $state('');
	let logicalSort = $state('');
	let scope = $state<LineScope | ''>('');
	let isComment = $state(false);
	let parts = $state<LinePartInput[]>([]);

	// The logical sort is optional (empty = "none"), but a non-empty value must
	// name a real sort: the stored one may have been deleted since, leaving the
	// <select> blank on a stale value. Block saving that rather than PATCHing an
	// invalid logical_sort for a backend 4xx. Moot for commentary, which sends
	// no sort at all.
	const logicalSortValid = $derived(
		isComment || logicalSort === '' || sortNames.includes(logicalSort)
	);
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
			scope = item?.scope ?? '';
			isComment = item?.behaviour === 'comment';
			parts = item?.parts.map((p) => ({ name: p.name, regex: p.regex })) ?? [];
		},
		payload
	});

	function payload() {
		return {
			name: name.trim(),
			shape: shape.trim(),
			behaviour: isComment ? ('comment' as const) : ('logical' as const),
			// Cleared, not merely hidden, when commentary: a comment bears no
			// formula and opens no scope, and the API rejects either pairing — so a
			// retained value would fail the save. (Contrast RulesSection, where the
			// hidden flag is only inert, and so survives.)
			logical_sort: isComment ? null : logicalSort || null,
			scope: isComment ? null : scope || null,
			parts: parts
				.filter((p) => p.name.trim() && p.regex.trim())
				.map((p) => ({ name: p.name.trim(), regex: p.regex.trim() }))
		};
	}
</script>

<!-- A system may declare several logical line types; the engine tries each when
	parsing a proof line. -->
<PartSection
	title="Line types"
	itemLabel={(l) => `line type ${l.name}`}
	id="line-types"
	addLabel="Add line type"
	items={lines}
	emptyMessage="No line types yet — these define the shapes a proof line may take."
	onAdd={s.openNew}
	onEdit={s.openEdit}
	onReorder={s.reorder}
	busy={s.busy}
>
	{#snippet row(l)}
		<div class="min-w-0 text-sm">
			<span class="font-medium">{l.name}</span>
			<span class="ml-2 font-mono text-xs text-muted-foreground">{l.shape}</span>
			{#if l.behaviour === 'comment'}
				<span class="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
					>commentary</span
				>
			{/if}
			{#if l.scope}
				<span class="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
					>opens {l.scope}</span
				>
			{/if}
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
	{notation}
	{symbols}
>
	<FormField label="Name" id="line-name" bind:value={name} placeholder="e.g. statement" maxlength={128} />
	<div class="space-y-2">
		<Label for="line-shape">Shape</Label>
		<Input id="line-shape" bind:value={shape} class="font-mono" data-symbol-field placeholder="e.g. <formula> [<reference>]" maxlength={256} />
	</div>
	<div class="space-y-2">
		<div class="flex items-center justify-between">
			<Label>Commentary</Label>
			<Button
				type="button"
				size="sm"
				variant={isComment ? 'default' : 'outline'}
				onclick={() => (isComment = !isComment)}
			>
				{isComment ? 'Enabled' : 'Off'}
			</Button>
		</div>
		<p class="text-xs text-muted-foreground">
			Prose the checker ignores. It is never numbered, so no citation can name it
			and inserting one never renumbers the steps around it. Its shape is free
			text — unlike a logical line, it need not contain a sort.
		</p>
	</div>
	{#if !isComment}
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
		<div class="space-y-2">
			<Label for="line-scope">Opens scope <span class="text-muted-foreground">(optional)</span></Label>
			<select
				id="line-scope"
				bind:value={scope}
				class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
			>
				<option value="">— none —</option>
				<option value="assumption">assumption (hypothesis subproof)</option>
				<option value="variable">variable (fresh-variable subproof)</option>
			</select>
		</div>
	{/if}
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
			<Input bind:value={part.regex} class="font-mono" data-symbol-field placeholder="regex" maxlength={512} />
		{/snippet}
	</RepeatableRows>
</EditSheet>
