<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import { api, type BracketPair } from '$lib/api';
	import type { SymbolEntry } from '$lib/symbols';
	import type { NotationGroup } from '$lib/notation';
	import { createSectionController } from './section.svelte';

	let {
		systemId,
		brackets,
		symbols,
		onChanged,
		notation = []
	}: {
		systemId: string;
		brackets: BracketPair[];
		symbols: SymbolEntry[];
		onChanged: () => Promise<void> | void;
		/** Optional: the grammar reference shown in the edit sheet. */
		notation?: NotationGroup[];
	} = $props();

	let opening = $state('');
	let closing = $state('');
	const canSave = $derived(opening.trim().length > 0 && closing.trim().length > 0);

	const s = createSectionController<BracketPair, { opening: string; closing: string }>({
		crud: api.parts.brackets,
		systemId: () => systemId,
		noun: 'Brackets',
		onChanged: () => onChanged(),
		canSave: () => canSave,
		fill: (item) => {
			opening = item?.opening ?? '';
			closing = item?.closing ?? '';
		},
		payload: () => ({ opening: opening.trim(), closing: closing.trim() })
	});
</script>

<PartSection
	title="Brackets"
	itemLabel={(b) => `brackets ${b.opening} ${b.closing}`}
	id="brackets"
	addLabel="Add brackets"
	items={brackets}
	emptyMessage="No bracket pairs yet."
	onAdd={s.openNew}
	onEdit={s.openEdit}
	onReorder={s.reorder}
	busy={s.busy}
>
	{#snippet row(b)}
		<span class="font-mono text-sm">{b.opening} {b.closing}</span>
	{/snippet}
</PartSection>

<EditSheet
	open={s.open}
	onOpenChange={(o) => (s.open = o)}
	title={s.editing ? 'Edit brackets' : 'Add brackets'}
	onSave={s.save}
	onDelete={s.editing ? s.del : undefined}
	saving={s.saving}
	{canSave}
	{notation}
	{symbols}
>
	<FormField label="Opening" id="bracket-open" bind:value={opening} placeholder="(" maxlength={16} notation />
	<FormField label="Closing" id="bracket-close" bind:value={closing} placeholder=")" maxlength={16} notation />
</EditSheet>
