<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import BindingsEditor from './BindingsEditor.svelte';
	import RepeatableRows from './RepeatableRows.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { Button } from '$lib/components/ui/button';
	import { api, type Rule, type Binding, type RuleMatching } from '$lib/api';
	import { createSectionController } from './section.svelte';

	let {
		systemId,
		rules,
		onChanged
	}: { systemId: string; rules: Rule[]; onChanged: () => Promise<void> | void } = $props();

	// Antecedents and provisos are plain strings in the API; wrap each in a row so
	// it has a stable identity to key on (bare strings aren't unique and change as
	// you type).
	type StringRow = { value: string };

	let label = $state('');
	let name = $state('');
	let deduction = $state('');
	let matching = $state<RuleMatching>('structural');
	let antecedents = $state<StringRow[]>([]);
	let sideConditions = $state<StringRow[]>([]);
	let bindings = $state<Binding[]>([]);
	const canSave = $derived(
		label.trim().length > 0 && name.trim().length > 0 && deduction.trim().length > 0
	);

	const s = createSectionController<Rule, ReturnType<typeof payload>>({
		crud: api.parts.rules,
		systemId: () => systemId,
		noun: 'Rule',
		onChanged: () => onChanged(),
		canSave: () => canSave,
		fill: (item) => {
			label = item?.label ?? '';
			name = item?.name ?? '';
			deduction = item?.deduction ?? '';
			matching = item?.matching ?? 'structural';
			antecedents = item?.antecedents.map((v) => ({ value: v })) ?? [];
			sideConditions = item?.side_conditions.map((v) => ({ value: v })) ?? [];
			bindings = item?.bindings.map((b) => ({ ...b })) ?? [];
		},
		payload
	});

	function payload() {
		return {
			label: label.trim(),
			name: name.trim(),
			deduction: deduction.trim(),
			matching,
			antecedents: antecedents.map((a) => a.value.trim()).filter(Boolean),
			side_conditions: sideConditions.map((sc) => sc.value.trim()).filter(Boolean),
			bindings: bindings.filter((b) => b.var.trim() && b.sort.trim())
		};
	}

	const MATCHING_OPTIONS: { value: RuleMatching; label: string }[] = [
		{ value: 'structural', label: 'Structural' },
		{ value: 'string', label: 'String rewriting' }
	];
</script>

<PartSection
	title="Inference rules"
	addLabel="Add rule"
	items={rules}
	emptyMessage="No inference rules yet."
	onAdd={s.openNew}
	onEdit={s.openEdit}
	onReorder={s.reorder}
	busy={s.busy}
>
	{#snippet row(r)}
		<div class="min-w-0 text-sm">
			<span class="font-mono text-muted-foreground">{r.label}</span>
			<span class="ml-2 font-medium">{r.name}</span>
			{#if r.matching === 'string'}
				<span class="ml-2 text-xs text-muted-foreground">· string rewriting</span>
			{/if}
			<span class="ml-2 font-mono text-xs text-muted-foreground">
				{r.antecedents.join(' ; ') || '—'} ⊢ {r.deduction}
			</span>
		</div>
	{/snippet}
</PartSection>

<EditSheet
	open={s.open}
	onOpenChange={(o) => (s.open = o)}
	title={s.editing ? 'Edit rule' : 'Add rule'}
	onSave={s.save}
	onDelete={s.editing ? s.del : undefined}
	saving={s.saving}
	{canSave}
>
	<FormField label="Label" id="rule-label" bind:value={label} placeholder="e.g. MP" maxlength={64} />
	<FormField label="Name" id="rule-name" bind:value={name} placeholder="e.g. modus ponens" maxlength={128} />
	<RepeatableRows
		bind:items={antecedents}
		label="Antecedents"
		hint="(premises)"
		addLabel="Add premise"
		removeLabel="Remove premise"
		blank={() => ({ value: '' })}
	>
		{#snippet row(antecedent)}
			<Input bind:value={antecedent.value} class="font-mono" placeholder="e.g. (p → q)" maxlength={512} />
		{/snippet}
	</RepeatableRows>
	<div class="space-y-2">
		<Label for="rule-deduction">Conclusion</Label>
		<Input id="rule-deduction" bind:value={deduction} class="font-mono" placeholder="e.g. q" maxlength={512} />
	</div>
	<div class="space-y-2">
		<Label>Checking</Label>
		<div class="flex gap-2">
			{#each MATCHING_OPTIONS as option (option.value)}
				<Button
					type="button"
					size="sm"
					variant={matching === option.value ? 'default' : 'outline'}
					onclick={() => (matching = option.value)}
				>
					{option.label}
				</Button>
			{/each}
		</div>
		<p class="text-xs text-muted-foreground">
			{#if matching === 'string'}
				Steps are checked by associative string matching — for rewriting systems (e.g. MIU)
				whose rules split and concatenate strings. Side-conditions do not apply.
			{:else}
				Steps are checked by term unification, where a variable binds a whole subterm (the
				default, for logical systems).
			{/if}
		</p>
	</div>
	<BindingsEditor bind:bindings />
	<RepeatableRows
		bind:items={sideConditions}
		label="Side-conditions"
		hint="(provisos)"
		description="All lines must hold; within a line, combine predicates with 'or'."
		addLabel="Add proviso"
		removeLabel="Remove proviso"
		blank={() => ({ value: '' })}
	>
		{#snippet row(proviso)}
			<Input bind:value={proviso.value} class="font-mono" placeholder="e.g. not occurs(x, p)" maxlength={512} />
		{/snippet}
	</RepeatableRows>
</EditSheet>
