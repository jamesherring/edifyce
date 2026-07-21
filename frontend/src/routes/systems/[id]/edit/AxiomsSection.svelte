<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import BindingsEditor from './BindingsEditor.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { api, ApiError, type Axiom, type Binding } from '$lib/api';
	import { toastSuccess, toastError } from '$lib/toast';

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
		if (!label.trim() || !name.trim() || !formula.trim() || saving) return;
		saving = true;
		const payload = {
			label: label.trim(),
			name: name.trim(),
			formula: formula.trim(),
			bindings: bindings.filter((b) => b.var.trim() && b.sort.trim())
		};
		try {
			if (editing) await api.parts.axioms.update(systemId, editing.id, payload);
			else await api.parts.axioms.create(systemId, payload);
			toastSuccess(editing ? 'Axiom updated.' : 'Axiom added.');
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
			await api.parts.axioms.remove(systemId, editing.id);
			toastSuccess('Axiom deleted.');
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
			await api.parts.axioms.reorder(systemId, ids);
			await onChanged();
		} catch (err) {
			toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			busy = false;
		}
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
>
	<FormField label="Label" id="axiom-label" bind:value={label} placeholder="e.g. EXT" maxlength={64} />
	<FormField label="Name" id="axiom-name" bind:value={name} placeholder="e.g. extensionality" maxlength={128} />
	<div class="space-y-2">
		<Label for="axiom-formula">Formula</Label>
		<Input id="axiom-formula" bind:value={formula} class="font-mono" placeholder="e.g. ∀x x = x" maxlength={512} />
	</div>
	<BindingsEditor bind:bindings />
</EditSheet>
