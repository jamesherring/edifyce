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
	import { api, type Rule, type Binding } from '$lib/api';
	import { runMutation } from './crud';

	let {
		systemId,
		rules,
		onChanged
	}: { systemId: string; rules: Rule[]; onChanged: () => Promise<void> | void } = $props();

	// Antecedents are plain strings in the API; wrap them so each row has a stable
	// identity to key on (bare strings aren't unique and change as you type).
	type Premise = { value: string };

	let open = $state(false);
	let editing = $state<Rule | null>(null);
	let label = $state('');
	let name = $state('');
	let deduction = $state('');
	let antecedents = $state<Premise[]>([]);
	let bindings = $state<Binding[]>([]);
	let saving = $state(false);
	let busy = $state(false);

	const canSave = $derived(
		label.trim().length > 0 && name.trim().length > 0 && deduction.trim().length > 0
	);

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
		antecedents = r.antecedents.map((v) => ({ value: v }));
		bindings = r.bindings.map((b) => ({ ...b }));
		open = true;
	}

	async function save() {
		if (!canSave || saving) return;
		saving = true;
		const item = editing;
		const payload = {
			label: label.trim(),
			name: name.trim(),
			deduction: deduction.trim(),
			antecedents: antecedents.map((a) => a.value.trim()).filter(Boolean),
			bindings: bindings.filter((b) => b.var.trim() && b.sort.trim())
		};
		const ok = await runMutation(
			() =>
				item
					? api.parts.rules.update(systemId, item.id, payload)
					: api.parts.rules.create(systemId, payload),
			item ? 'Rule updated.' : 'Rule added.'
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
			() => api.parts.rules.remove(systemId, editing!.id),
			'Rule deleted.'
		);
		saving = false;
		if (ok) {
			open = false;
			await onChanged();
		}
	}

	async function reorder(ids: string[]) {
		busy = true;
		if (await runMutation(() => api.parts.rules.reorder(systemId, ids))) await onChanged();
		busy = false;
	}

	function addAntecedent() {
		antecedents = [...antecedents, { value: '' }];
	}
	function removeAntecedent(premise: Premise) {
		antecedents = antecedents.filter((a) => a !== premise);
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
	{canSave}
>
	<FormField label="Label" id="rule-label" bind:value={label} placeholder="e.g. MP" maxlength={64} />
	<FormField label="Name" id="rule-name" bind:value={name} placeholder="e.g. modus ponens" maxlength={128} />
	<div class="space-y-2">
		<Label>Antecedents <span class="text-muted-foreground">(premises)</span></Label>
		{#each antecedents as antecedent (antecedent)}
			<div class="flex items-center gap-2">
				<Input bind:value={antecedent.value} class="font-mono" placeholder="e.g. (p → q)" maxlength={512} />
				<Button
					type="button"
					variant="ghost"
					size="icon"
					class="shrink-0"
					onclick={() => removeAntecedent(antecedent)}
				>
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
