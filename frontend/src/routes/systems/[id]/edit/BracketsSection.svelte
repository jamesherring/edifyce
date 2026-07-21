<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import { api, ApiError, type BracketPair } from '$lib/api';
	import { toastSuccess, toastError } from '$lib/toast';

	let {
		systemId,
		brackets,
		onChanged
	}: { systemId: string; brackets: BracketPair[]; onChanged: () => Promise<void> | void } =
		$props();

	let open = $state(false);
	let editing = $state<BracketPair | null>(null);
	let opening = $state('');
	let closing = $state('');
	let saving = $state(false);
	let busy = $state(false);

	function openNew() {
		editing = null;
		opening = '';
		closing = '';
		open = true;
	}
	function openEdit(b: BracketPair) {
		editing = b;
		opening = b.opening;
		closing = b.closing;
		open = true;
	}

	async function save() {
		if (!opening.trim() || !closing.trim() || saving) return;
		saving = true;
		const payload = { opening: opening.trim(), closing: closing.trim() };
		try {
			if (editing) await api.parts.brackets.update(systemId, editing.id, payload);
			else await api.parts.brackets.create(systemId, payload);
			toastSuccess(editing ? 'Brackets updated.' : 'Brackets added.');
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
			await api.parts.brackets.remove(systemId, editing.id);
			toastSuccess('Brackets deleted.');
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
			await api.parts.brackets.reorder(systemId, ids);
			await onChanged();
		} catch (err) {
			toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			busy = false;
		}
	}
</script>

<PartSection
	title="Brackets"
	addLabel="Add brackets"
	items={brackets}
	emptyMessage="No bracket pairs yet."
	onAdd={openNew}
	onEdit={openEdit}
	onReorder={reorder}
	{busy}
>
	{#snippet row(b)}
		<span class="font-mono text-sm">{b.opening} {b.closing}</span>
	{/snippet}
</PartSection>

<EditSheet
	{open}
	onOpenChange={(o) => (open = o)}
	title={editing ? 'Edit brackets' : 'Add brackets'}
	onSave={save}
	onDelete={editing ? del : undefined}
	{saving}
>
	<FormField label="Opening" id="bracket-open" bind:value={opening} placeholder="(" maxlength={16} />
	<FormField label="Closing" id="bracket-close" bind:value={closing} placeholder=")" maxlength={16} />
</EditSheet>
