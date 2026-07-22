<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import { api, type Sort } from '$lib/api';
	import { runMutation } from './crud';

	let {
		systemId,
		sorts,
		onChanged
	}: { systemId: string; sorts: Sort[]; onChanged: () => Promise<void> | void } = $props();

	let open = $state(false);
	let editing = $state<Sort | null>(null);
	let name = $state('');
	let saving = $state(false);
	let busy = $state(false);

	const canSave = $derived(name.trim().length > 0);

	function openNew() {
		editing = null;
		name = '';
		open = true;
	}
	function openEdit(s: Sort) {
		editing = s;
		name = s.name;
		open = true;
	}

	async function save() {
		if (!canSave || saving) return;
		saving = true;
		const item = editing;
		const ok = await runMutation(
			() =>
				item
					? api.parts.sorts.update(systemId, item.id, { name: name.trim() })
					: api.parts.sorts.create(systemId, { name: name.trim() }),
			item ? 'Sort updated.' : 'Sort added.'
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
			() => api.parts.sorts.remove(systemId, editing!.id),
			'Sort deleted.'
		);
		saving = false;
		if (ok) {
			open = false;
			await onChanged();
		}
	}

	async function reorder(ids: string[]) {
		busy = true;
		if (await runMutation(() => api.parts.sorts.reorder(systemId, ids))) await onChanged();
		busy = false;
	}
</script>

<PartSection
	title="Sorts"
	addLabel="Add sort"
	items={sorts}
	emptyMessage="No sorts yet — a sort is a syntactic category like “term” or “formula”."
	onAdd={openNew}
	onEdit={openEdit}
	onReorder={reorder}
	{busy}
>
	{#snippet row(s)}
		<span class="font-mono text-sm">{s.name}</span>
	{/snippet}
</PartSection>

<EditSheet
	{open}
	onOpenChange={(o) => (open = o)}
	title={editing ? 'Edit sort' : 'Add sort'}
	onSave={save}
	onDelete={editing ? del : undefined}
	{saving}
	{canSave}
>
	<FormField label="Name" id="sort-name" bind:value={name} placeholder="e.g. term" maxlength={128} />
</EditSheet>
