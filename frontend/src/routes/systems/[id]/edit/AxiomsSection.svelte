<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import BindingsEditor from './BindingsEditor.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { api, type Axiom, type Binding } from '$lib/api';
	import { runMutation } from './crud';

	let {
		systemId,
		axioms,
		onChanged
	}: { systemId: string; axioms: Axiom[]; onChanged: () => Promise<void> | void } = $props();

	let open = $state(false);
	let editing = $state<Axiom | null>(null);
	let label = $state('');
	let name = $state('');
	let formula = $state('');
	let bindings = $state<Binding[]>([]);
	let saving = $state(false);
	let busy = $state(false);

	const canSave = $derived(
		label.trim().length > 0 && name.trim().length > 0 && formula.trim().length > 0
	);

	function openNew() {
		editing = null;
		label = '';
		name = '';
		formula = '';
		bindings = [];
		open = true;
	}
	function openEdit(a: Axiom) {
		editing = a;
		label = a.label;
		name = a.name;
		formula = a.formula;
		bindings = a.bindings.map((b) => ({ ...b }));
		open = true;
	}

	async function save() {
		if (!canSave || saving) return;
		saving = true;
		const item = editing;
		const payload = {
			label: label.trim(),
			name: name.trim(),
			formula: formula.trim(),
			bindings: bindings.filter((b) => b.var.trim() && b.sort.trim())
		};
		const ok = await runMutation(
			() =>
				item
					? api.parts.axioms.update(systemId, item.id, payload)
					: api.parts.axioms.create(systemId, payload),
			item ? 'Axiom updated.' : 'Axiom added.'
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
			() => api.parts.axioms.remove(systemId, editing!.id),
			'Axiom deleted.'
		);
		saving = false;
		if (ok) {
			open = false;
			await onChanged();
		}
	}

	async function reorder(ids: string[]) {
		busy = true;
		if (await runMutation(() => api.parts.axioms.reorder(systemId, ids))) await onChanged();
		busy = false;
	}
</script>

<PartSection
	title="Axioms"
	addLabel="Add axiom"
	items={axioms}
	emptyMessage="No axioms yet."
	onAdd={openNew}
	onEdit={openEdit}
	onReorder={reorder}
	{busy}
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
	{open}
	onOpenChange={(o) => (open = o)}
	title={editing ? 'Edit axiom' : 'Add axiom'}
	onSave={save}
	onDelete={editing ? del : undefined}
	{saving}
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
