<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import BindingsEditor from './BindingsEditor.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { Button } from '$lib/components/ui/button';
	import X from '@lucide/svelte/icons/x';
	import Plus from '@lucide/svelte/icons/plus';
	import { api, ApiError, type Rule, type Binding } from '$lib/api';
	import { toastSuccess, toastError } from '$lib/toast';

	let {
		systemId,
		rules,
		onChanged
	}: { systemId: string; rules: Rule[]; onChanged: () => Promise<void> | void } = $props();

	let open = $state(false);
	let editing = $state<Rule | null>(null);
	let label = $state('');
	let name = $state('');
	let deduction = $state('');
	let antecedents = $state<string[]>([]);
	let bindings = $state<Binding[]>([]);
	let saving = $state(false);
	let busy = $state(false);

	function openNew() {
		editing = null;
		label = '';
		name = '';
		deduction = '';
		antecedents = [];
		bindings = [];
		open = true;
	}
	function openEdit(r: Rule) {
		editing = r;
		label = r.label;
		name = r.name;
		deduction = r.deduction;
		antecedents = [...r.antecedents];
		bindings = r.bindings.map((b) => ({ ...b }));
		open = true;
	}

	async function save() {
		if (!label.trim() || !name.trim() || !deduction.trim() || saving) return;
		saving = true;
		const payload = {
			label: label.trim(),
			name: name.trim(),
			deduction: deduction.trim(),
			antecedents: antecedents.map((a) => a.trim()).filter(Boolean),
			bindings: bindings.filter((b) => b.var.trim() && b.sort.trim())
		};
		try {
			if (editing) await api.parts.rules.update(systemId, editing.id, payload);
			else await api.parts.rules.create(systemId, payload);
			toastSuccess(editing ? 'Rule updated.' : 'Rule added.');
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
			await api.parts.rules.remove(systemId, editing.id);
			toastSuccess('Rule deleted.');
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
			await api.parts.rules.reorder(systemId, ids);
			await onChanged();
		} catch (err) {
			toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			busy = false;
		}
	}

	function addAntecedent() {
		antecedents = [...antecedents, ''];
	}
	function removeAntecedent(i: number) {
		antecedents = antecedents.filter((_, idx) => idx !== i);
	}
</script>

<PartSection
	title="Inference rules"
	addLabel="Add rule"
	items={rules}
	emptyMessage="No inference rules yet."
	onAdd={openNew}
	onEdit={openEdit}
	onReorder={reorder}
	{busy}
>
	{#snippet row(r)}
		<div class="min-w-0 text-sm">
			<span class="font-mono text-muted-foreground">{r.label}</span>
			<span class="ml-2 font-medium">{r.name}</span>
			<span class="ml-2 font-mono text-xs text-muted-foreground">
				{r.antecedents.join(' ; ') || '—'} ⊢ {r.deduction}
			</span>
		</div>
	{/snippet}
</PartSection>

<EditSheet
	{open}
	onOpenChange={(o) => (open = o)}
	title={editing ? 'Edit rule' : 'Add rule'}
	onSave={save}
	onDelete={editing ? del : undefined}
	{saving}
>
	<FormField label="Label" id="rule-label" bind:value={label} placeholder="e.g. MP" maxlength={64} />
	<FormField label="Name" id="rule-name" bind:value={name} placeholder="e.g. modus ponens" maxlength={128} />
	<div class="space-y-2">
		<Label>Antecedents <span class="text-muted-foreground">(premises)</span></Label>
		{#each antecedents as _a, i (i)}
			<div class="flex items-center gap-2">
				<Input bind:value={antecedents[i]} class="font-mono" placeholder="e.g. (p → q)" maxlength={512} />
				<Button type="button" variant="ghost" size="icon" class="shrink-0" onclick={() => removeAntecedent(i)}>
					<X class="size-4" /><span class="sr-only">Remove premise</span>
				</Button>
			</div>
		{/each}
		<Button type="button" variant="outline" size="sm" onclick={addAntecedent}>
			<Plus class="size-4" /> Add premise
		</Button>
	</div>
	<div class="space-y-2">
		<Label for="rule-deduction">Conclusion</Label>
		<Input id="rule-deduction" bind:value={deduction} class="font-mono" placeholder="e.g. q" maxlength={512} />
	</div>
	<BindingsEditor bind:bindings />
</EditSheet>
