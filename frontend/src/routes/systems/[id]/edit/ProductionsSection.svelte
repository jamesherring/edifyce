<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import BindingsEditor from './BindingsEditor.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { api, ApiError, type Production, type Binding } from '$lib/api';
	import { toastSuccess, toastError } from '$lib/toast';

	let {
		systemId,
		productions,
		sortNames,
		onChanged
	}: {
		systemId: string;
		productions: Production[];
		sortNames: string[];
		onChanged: () => Promise<void> | void;
	} = $props();

	let open = $state(false);
	let editing = $state<Production | null>(null);
	let name = $state('');
	let sortName = $state('');
	let mode = $state<'template' | 'regex'>('template');
	let value = $state('');
	let bindings = $state<Binding[]>([]);
	let saving = $state(false);
	let busy = $state(false);

	function openNew() {
		editing = null;
		name = '';
		sortName = sortNames[0] ?? '';
		mode = 'template';
		value = '';
		bindings = [];
		open = true;
	}
	function openEdit(p: Production) {
		editing = p;
		name = p.name;
		sortName = p.sort;
		mode = p.template !== null ? 'template' : 'regex';
		value = p.template ?? p.regex ?? '';
		bindings = p.bindings.map((b) => ({ ...b }));
		open = true;
	}

	async function save() {
		if (!name.trim() || !sortName || !value.trim() || saving) return;
		saving = true;
		// Send both fields with the inactive one nulled so switching template↔regex
		// clears the other; the backend requires exactly one to be set.
		const payload = {
			name: name.trim(),
			sort: sortName,
			template: mode === 'template' ? value.trim() : null,
			regex: mode === 'regex' ? value.trim() : null,
			bindings: bindings.filter((b) => b.var.trim() && b.sort.trim())
		};
		try {
			if (editing) await api.parts.productions.update(systemId, editing.id, payload);
			else await api.parts.productions.create(systemId, payload);
			toastSuccess(editing ? 'Production updated.' : 'Production added.');
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
			await api.parts.productions.remove(systemId, editing.id);
			toastSuccess('Production deleted.');
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
			await api.parts.productions.reorder(systemId, ids);
			await onChanged();
		} catch (err) {
			toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			busy = false;
		}
	}
</script>

<PartSection
	title="Grammar"
	addLabel="Add production"
	items={productions}
	emptyMessage="No productions yet — these define the concrete syntax of each sort."
	onAdd={openNew}
	onEdit={openEdit}
	onReorder={reorder}
	{busy}
>
	{#snippet row(p)}
		<div class="min-w-0 text-sm">
			<span class="font-medium">{p.name}</span>
			<span class="text-muted-foreground"> : {p.sort}</span>
			<span class="ml-2 font-mono text-xs text-muted-foreground">
				{p.template ?? `matches ${p.regex}`}
			</span>
		</div>
	{/snippet}
</PartSection>

<EditSheet
	{open}
	onOpenChange={(o) => (open = o)}
	title={editing ? 'Edit production' : 'Add production'}
	onSave={save}
	onDelete={editing ? del : undefined}
	{saving}
>
	<FormField label="Name" id="prod-name" bind:value={name} placeholder="e.g. implication" maxlength={128} />
	<div class="space-y-2">
		<Label for="prod-sort">Sort</Label>
		<select
			id="prod-sort"
			bind:value={sortName}
			class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
		>
			{#if sortNames.length === 0}
				<option value="" disabled>Add a sort first</option>
			{/if}
			{#each sortNames as s (s)}
				<option value={s}>{s}</option>
			{/each}
		</select>
	</div>
	<div class="space-y-2">
		<Label>Rule</Label>
		<div class="inline-flex rounded-md border p-0.5 text-sm">
			<button
				type="button"
				onclick={() => (mode = 'template')}
				class={[
					'rounded px-3 py-1',
					mode === 'template' ? 'bg-accent text-accent-foreground' : 'text-muted-foreground'
				]}
			>
				Template
			</button>
			<button
				type="button"
				onclick={() => (mode = 'regex')}
				class={[
					'rounded px-3 py-1',
					mode === 'regex' ? 'bg-accent text-accent-foreground' : 'text-muted-foreground'
				]}
			>
				Regex
			</button>
		</div>
		<Input
			bind:value
			class="font-mono"
			placeholder={mode === 'template' ? 'e.g. (p → q)' : 'e.g. [a-z][a-z0-9]*'}
			maxlength={512}
		/>
	</div>
	<BindingsEditor bind:bindings />
</EditSheet>
