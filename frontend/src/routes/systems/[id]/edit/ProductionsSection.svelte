<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import BindingsEditor from './BindingsEditor.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { api, type Production, type Binding } from '$lib/api';
	import { createSectionController } from './section.svelte';

	let {
		systemId,
		productions,
		sortNames,
		onChanged
	}: {
		systemId: string;
		productions: Production[];
		sortNames: string[];
		onChanged: () => Promise<void> | void;
	} = $props();

	let name = $state('');
	let sortName = $state('');
	let mode = $state<'template' | 'regex'>('template');
	let value = $state('');
	let bindings = $state<Binding[]>([]);

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
			mode = item && item.template === null ? 'regex' : 'template';
			value = item ? (item.template ?? item.regex ?? '') : '';
			bindings = item?.bindings.map((b) => ({ ...b })) ?? [];
		},
		payload
	});

	function payload() {
		// Send both fields with the inactive one nulled so switching template↔regex
		// clears the other; the backend requires exactly one to be set.
		return {
			name: name.trim(),
			sort: sortName,
			template: mode === 'template' ? value.trim() : null,
			regex: mode === 'regex' ? value.trim() : null,
			bindings: bindings.filter((b) => b.var.trim() && b.sort.trim())
		};
	}
</script>

<PartSection
	title="Grammar"
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
				{p.template ?? `matches ${p.regex}`}
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
		<div class="inline-flex rounded-md border p-0.5 text-sm">
			<button
				type="button"
				onclick={() => (mode = 'template')}
				class={[
					'rounded px-3 py-1',
					mode === 'template' ? 'bg-accent text-accent-foreground' : 'text-muted-foreground'
				]}
			>
				Template
			</button>
			<button
				type="button"
				onclick={() => (mode = 'regex')}
				class={[
					'rounded px-3 py-1',
					mode === 'regex' ? 'bg-accent text-accent-foreground' : 'text-muted-foreground'
				]}
			>
				Regex
			</button>
		</div>
		<Input
			bind:value
			class="font-mono"
			placeholder={mode === 'template' ? 'e.g. (p → q)' : 'e.g. [a-z][a-z0-9]*'}
			maxlength={512}
		/>
	</div>
	<BindingsEditor bind:bindings />
</EditSheet>
