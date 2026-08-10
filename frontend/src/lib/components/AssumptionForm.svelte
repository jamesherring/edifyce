<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Textarea } from '$lib/components/ui/textarea';
	import * as Alert from '$lib/components/ui/alert';
	import RepeatableRows from '$lib/components/RepeatableRows.svelte';
	import SymbolPalette from '$lib/components/SymbolPalette.svelte';
	import { api, ApiError, type Assumption } from '$lib/api';
	import type { SymbolEntry } from '$lib/symbols';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';

	// Taking a debt on, with the editorial record the checker has no opinion
	// about. The statement is source text in the system's own grammar — the same
	// form a corpus import gives a theorem — so this is deliberately the same set
	// of fields a promotion carries, plus `reason` and `source`.
	let {
		systemId,
		symbols = [],
		oncreated,
		oncancel
	}: {
		systemId: string;
		/** The system's own notation, to lead the palette with. */
		symbols?: SymbolEntry[];
		oncreated: (assumption: Assumption) => void;
		oncancel: () => void;
	} = $props();

	// The palette types into this form's `data-symbol-field` inputs, and needs the
	// element to find them. Without it those attributes would be decoration: there
	// is no other way to enter the `→` in the statement placeholder.
	let form = $state<HTMLFormElement | null>(null);

	let label = $state('');
	let statement = $state('');
	let reason = $state('');
	let source = $state('');
	// Wrapped in objects rather than held as bare strings: `RepeatableRows` keys
	// rows by identity, so two empty rows must be two distinct values.
	let premises = $state<{ value: string }[]>([]);
	let metavariables = $state<{ var: string; sort: string }[]>([]);
	let distinct = $state<{ value: string }[]>([]);
	let saving = $state(false);
	let error = $state<string | null>(null);

	// `reason` is required by the API and the reason is the point: an assumption
	// with no reason is an axiom nobody remembers adopting.
	const canSave = $derived(
		label.trim().length > 0 && statement.trim().length > 0 && reason.trim().length > 0
	);

	function filled(rows: { value: string }[]): string[] {
		return rows.map((row) => row.value.trim()).filter((value) => value.length > 0);
	}

	async function save(event: SubmitEvent) {
		event.preventDefault();
		if (!canSave || saving) return;
		saving = true;
		error = null;
		let created: Assumption;
		try {
			created = await api.assumptions.create(systemId, {
				label: label.trim(),
				statement: statement.trim(),
				premises: filled(premises),
				metavariables: Object.fromEntries(
					metavariables
						.map((row) => [row.var.trim(), row.sort.trim()] as const)
						.filter(([name, sort]) => name.length > 0 && sort.length > 0)
				),
				distinct: filled(distinct),
				reason: reason.trim(),
				source: source.trim() || null
			});
		} catch (err) {
			// Every refusal here is worth reading verbatim: a label already taken, a
			// label an inference rule owns, or a statement the grammar cannot read.
			error = err instanceof ApiError ? err.message : String(err);
			saving = false;
			return;
		}
		// Outside the try: the assumption exists by now, and a throw from the host's
		// callback reported as a refusal would say the opposite.
		saving = false;
		oncreated(created);
	}
</script>

<form bind:this={form} class="flex flex-col gap-4 rounded-lg border p-4" onsubmit={save}>
	<SymbolPalette root={form} {symbols} />

	{#if error}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>Could not take this on</Alert.Title>
			<Alert.Description>{error}</Alert.Description>
		</Alert.Root>
	{/if}

	<div class="space-y-2">
		<Label for="assumption-label">Label</Label>
		<Input
			id="assumption-label"
			bind:value={label}
			class="font-mono"
			placeholder="e.g. lemma-2-1"
			maxlength={128}
		/>
		<p class="text-xs text-muted-foreground">
			What a proof cites it by. Proving it later and promoting the proof under this same
			label discharges the assumption rather than leaving it beside the theorem.
		</p>
	</div>

	<div class="space-y-2">
		<Label for="assumption-statement">Statement</Label>
		<Textarea
			id="assumption-statement"
			bind:value={statement}
			rows={2}
			class="font-mono"
			data-symbol-field
			placeholder="e.g. (p → (q → p))"
		/>
		<p class="text-xs text-muted-foreground">
			Written in this system's own notation, as a theorem's is.
		</p>
	</div>

	<RepeatableRows
		bind:items={premises}
		label="Premises"
		hint="(optional)"
		description="Hypotheses a citation must supply, in order."
		addLabel="Add premise"
		removeLabel="Remove premise"
		blank={() => ({ value: '' })}
	>
		{#snippet row(premise)}
			<Input
				bind:value={premise.value}
				class="font-mono"
				data-symbol-field
				placeholder="e.g. p"
				maxlength={512}
			/>
		{/snippet}
	</RepeatableRows>

	<RepeatableRows
		bind:items={metavariables}
		label="Metavariables"
		hint="(optional)"
		description="Leaves that stand for any term of a sort, making this a schema rather than one statement."
		addLabel="Add metavariable"
		removeLabel="Remove metavariable"
		blank={() => ({ var: '', sort: '' })}
	>
		{#snippet row(metavariable)}
			<Input bind:value={metavariable.var} placeholder="var" class="font-mono" />
			<span class="text-muted-foreground">:</span>
			<Input bind:value={metavariable.sort} placeholder="sort" class="font-mono" />
		{/snippet}
	</RepeatableRows>

	<RepeatableRows
		bind:items={distinct}
		label="Distinct variables"
		hint="(optional)"
		description="One disjoint(…) line each, as a rule's provisos are written."
		addLabel="Add proviso"
		removeLabel="Remove proviso"
		blank={() => ({ value: '' })}
	>
		{#snippet row(proviso)}
			<Input
				bind:value={proviso.value}
				class="font-mono"
				data-symbol-field
				placeholder="e.g. disjoint(x, p)"
				maxlength={512}
			/>
		{/snippet}
	</RepeatableRows>

	<div class="space-y-2">
		<Label for="assumption-reason">Reason</Label>
		<Textarea
			id="assumption-reason"
			bind:value={reason}
			rows={2}
			placeholder="Why it is believed true, and why it is not proved here."
		/>
		<p class="text-xs text-muted-foreground">
			Required. An assumption with no reason is an axiom nobody remembers adopting.
		</p>
	</div>

	<div class="space-y-2">
		<Label for="assumption-source">
			Source <span class="text-muted-foreground">(optional)</span>
		</Label>
		<Input
			id="assumption-source"
			bind:value={source}
			placeholder="A DOI, arXiv id, URL or textbook reference"
		/>
	</div>

	<div class="flex justify-end gap-2">
		<Button type="button" variant="ghost" onclick={oncancel} disabled={saving}>Cancel</Button>
		<Button type="submit" disabled={!canSave || saving}>
			{#if saving}
				<LoaderCircle class="size-4 animate-spin" /> Taking on…
			{:else}
				Take on
			{/if}
		</Button>
	</div>
</form>
