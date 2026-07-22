<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import BindingsEditor from './BindingsEditor.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { api, type Definition, type Binding } from '$lib/api';
	import { runMutation } from './crud';

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

	let open = $state(false);
	let editing = $state<Definition | null>(null);
	let sortName = $state('');
	let name = $state('');
	let higher = $state('');
	let lower = $state('');
	let condition = $state('');
	let bindings = $state<Binding[]>([]);
	let saving = $state(false);
	let busy = $state(false);

	const canSave = $derived(
		!!sortName && name.trim().length > 0 && higher.trim().length > 0 && lower.trim().length > 0
	);

	function openNew() {
		editing = null;
		sortName = sortNames[0] ?? '';
		name = '';
		higher = '';
		lower = '';
		condition = '';
		bindings = [];
		open = true;
	}
	function openEdit(d: Definition) {
		editing = d;
		sortName = d.sort;
		name = d.name;
		higher = d.higher;
		lower = d.lower;
		condition = d.condition ?? '';
		bindings = d.bindings.map((b) => ({ ...b }));
		open = true;
	}

	async function save() {
		if (!canSave || saving) return;
		saving = true;
		const item = editing;
		const payload = {
			sort: sortName,
			name: name.trim(),
			higher: higher.trim(),
			lower: lower.trim(),
			condition: condition.trim() || null,
			bindings: bindings.filter((b) => b.var.trim() && b.sort.trim())
		};
		const ok = await runMutation(
			() =>
				item
					? api.parts.definitions.update(systemId, item.id, payload)
					: api.parts.definitions.create(systemId, payload),
			item ? 'Definition updated.' : 'Definition added.'
		);
		saving = false;
		if (ok) {
			open = false;
			await onChanged();
		}
	}

	async function del() {
		if (!editing || saving) return;
		saving = true;
		const ok = await runMutation(
			() => api.parts.definitions.remove(systemId, editing!.id),
			'Definition deleted.'
		);
		saving = false;
		if (ok) {
			open = false;
			await onChanged();
		}
	}

	async function reorder(ids: string[]) {
		busy = true;
		if (await runMutation(() => api.parts.definitions.reorder(systemId, ids))) await onChanged();
		busy = false;
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
	onAdd={openNew}
	onEdit={openEdit}
	onReorder={reorder}
	{busy}
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
	{open}
	onOpenChange={(o) => (open = o)}
	title={editing ? 'Edit definition' : 'Add definition'}
	onSave={save}
	onDelete={editing ? del : undefined}
	{saving}
	{canSave}
>
	<div class="space-y-2">
		<Label for="def-sort">Sort</Label>
		<select
			id="def-sort"
			bind:value={sortName}
			class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
		>
			{#each sortNames as s (s)}
				<option value={s}>{s}</option>
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
