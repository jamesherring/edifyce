<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import BindingsEditor from './BindingsEditor.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { api, ApiError, type Definition, type Binding } from '$lib/api';
	import { toastSuccess, toastError } from '$lib/toast';

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
		if (!sortName || !name.trim() || !higher.trim() || !lower.trim() || saving) return;
		saving = true;
		const payload = {
			sort: sortName,
			name: name.trim(),
			higher: higher.trim(),
			lower: lower.trim(),
			condition: condition.trim() || null,
			bindings: bindings.filter((b) => b.var.trim() && b.sort.trim())
		};
		try {
			if (editing) await api.parts.definitions.update(systemId, editing.id, payload);
			else await api.parts.definitions.create(systemId, payload);
			toastSuccess(editing ? 'Definition updated.' : 'Definition added.');
			open = false;
			await onChanged();
		} catch (err) {
			toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			saving = false;
		}
	}

	async function del() {
		if (!editing || saving) return;
		saving = true;
		try {
			await api.parts.definitions.remove(systemId, editing.id);
			toastSuccess('Definition deleted.');
			open = false;
			await onChanged();
		} catch (err) {
			toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			saving = false;
		}
	}

	async function reorder(ids: string[]) {
		busy = true;
		try {
			await api.parts.definitions.reorder(systemId, ids);
			await onChanged();
		} catch (err) {
			toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			busy = false;
		}
	}
</script>

<PartSection
	title="Definitions"
	addLabel="Add definition"
	items={definitions}
	emptyMessage="No definitions yet."
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
>
	<div class="space-y-2">
		<Label for="def-sort">Sort</Label>
		<select
			id="def-sort"
			bind:value={sortName}
			class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
		>
			{#if sortNames.length === 0}
				<option value="" disabled>Add a sort first</option>
			{/if}
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
