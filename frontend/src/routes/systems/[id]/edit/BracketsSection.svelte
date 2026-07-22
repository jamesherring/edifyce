<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import { api, type BracketPair } from '$lib/api';
	import { runMutation } from './crud';

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

	const canSave = $derived(opening.trim().length > 0 && closing.trim().length > 0);

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
		if (!canSave || saving) return;
		saving = true;
		const item = editing;
		const payload = { opening: opening.trim(), closing: closing.trim() };
		const ok = await runMutation(
			() =>
				item
					? api.parts.brackets.update(systemId, item.id, payload)
					: api.parts.brackets.create(systemId, payload),
			item ? 'Brackets updated.' : 'Brackets added.'
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
			() => api.parts.brackets.remove(systemId, editing!.id),
			'Brackets deleted.'
		);
		saving = false;
		if (ok) {
			open = false;
			await onChanged();
		}
	}

	async function reorder(ids: string[]) {
		busy = true;
		if (await runMutation(() => api.parts.brackets.reorder(systemId, ids))) await onChanged();
		busy = false;
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
	{canSave}
>
	<FormField label="Opening" id="bracket-open" bind:value={opening} placeholder="(" maxlength={16} />
	<FormField label="Closing" id="bracket-close" bind:value={closing} placeholder=")" maxlength={16} />
</EditSheet>
