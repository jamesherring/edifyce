<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import { api, ApiError, type Sort } from '$lib/api';
	import { toastSuccess, toastError } from '$lib/toast';

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
		if (!name.trim() || saving) return;
		saving = true;
		try {
			if (editing) await api.parts.sorts.update(systemId, editing.id, { name: name.trim() });
			else await api.parts.sorts.create(systemId, { name: name.trim() });
			toastSuccess(editing ? 'Sort updated.' : 'Sort added.');
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
			await api.parts.sorts.remove(systemId, editing.id);
			toastSuccess('Sort deleted.');
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
			await api.parts.sorts.reorder(systemId, ids);
			await onChanged();
		} catch (err) {
			toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			busy = false;
		}
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
>
	<FormField label="Name" id="sort-name" bind:value={name} placeholder="e.g. term" maxlength={128} />
</EditSheet>
