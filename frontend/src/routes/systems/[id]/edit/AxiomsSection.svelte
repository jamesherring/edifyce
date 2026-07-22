<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import BindingsEditor from './BindingsEditor.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { api, type Axiom, type Binding } from '$lib/api';
	import { createSectionController } from './section.svelte';

	let {
		systemId,
		axioms,
		onChanged
	}: { systemId: string; axioms: Axiom[]; onChanged: () => Promise<void> | void } = $props();

	let label = $state('');
	let name = $state('');
	let formula = $state('');
	let bindings = $state<Binding[]>([]);
	const canSave = $derived(
		label.trim().length > 0 && name.trim().length > 0 && formula.trim().length > 0
	);

	const s = createSectionController<Axiom, ReturnType<typeof payload>>({
		crud: api.parts.axioms,
		systemId: () => systemId,
		noun: 'Axiom',
		onChanged: () => onChanged(),
		canSave: () => canSave,
		fill: (item) => {
			label = item?.label ?? '';
			name = item?.name ?? '';
			formula = item?.formula ?? '';
			bindings = item?.bindings.map((b) => ({ ...b })) ?? [];
		},
		payload
	});

	function payload() {
		return {
			label: label.trim(),
			name: name.trim(),
			formula: formula.trim(),
			bindings: bindings.filter((b) => b.var.trim() && b.sort.trim())
		};
	}
</script>

<PartSection
	title="Axioms"
	addLabel="Add axiom"
	items={axioms}
	emptyMessage="No axioms yet."
	onAdd={s.openNew}
	onEdit={s.openEdit}
	onReorder={s.reorder}
	busy={s.busy}
>
	{#snippet row(a)}
		<div class="min-w-0 text-sm">
			<span class="font-mono text-muted-foreground">{a.label}</span>
			<span class="ml-2 font-medium">{a.name}</span>
			<span class="ml-2 font-mono text-xs">{a.formula}</span>
		</div>
	{/snippet}
</PartSection>

<EditSheet
	open={s.open}
	onOpenChange={(o) => (s.open = o)}
	title={s.editing ? 'Edit axiom' : 'Add axiom'}
	onSave={s.save}
	onDelete={s.editing ? s.del : undefined}
	saving={s.saving}
	{canSave}
>
	<FormField label="Label" id="axiom-label" bind:value={label} placeholder="e.g. EXT" maxlength={64} />
	<FormField label="Name" id="axiom-name" bind:value={name} placeholder="e.g. extensionality" maxlength={128} />
	<div class="space-y-2">
		<Label for="axiom-formula">Formula</Label>
		<Input id="axiom-formula" bind:value={formula} class="font-mono" placeholder="e.g. ∀x x = x" maxlength={512} />
	</div>
	<BindingsEditor bind:bindings />
</EditSheet>
