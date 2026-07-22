<script lang="ts">
	import PartSection from './PartSection.svelte';
	import EditSheet from '$lib/components/EditSheet.svelte';
	import FormField from '$lib/components/FormField.svelte';
	import { Label } from '$lib/components/ui/label';
	import { Input } from '$lib/components/ui/input';
	import { Button } from '$lib/components/ui/button';
	import X from '@lucide/svelte/icons/x';
	import Plus from '@lucide/svelte/icons/plus';
	import { api, type LineType, type LinePartInput } from '$lib/api';
	import { runMutation } from './crud';

	let {
		systemId,
		lines,
		sortNames,
		onChanged
	}: {
		systemId: string;
		lines: LineType[];
		sortNames: string[];
		onChanged: () => Promise<void> | void;
	} = $props();

	let open = $state(false);
	let editing = $state<LineType | null>(null);
	let name = $state('');
	let shape = $state('');
	let logicalSort = $state('');
	let parts = $state<LinePartInput[]>([]);
	let saving = $state(false);

	// The logical sort is optional (empty = "none"), but a non-empty value must
	// name a real sort: the stored one may have been deleted since, leaving the
	// <select> blank on a stale value. Block saving that rather than PATCHing an
	// invalid logical_sort for a backend 4xx.
	const logicalSortValid = $derived(logicalSort === '' || sortNames.includes(logicalSort));
	const canSave = $derived(
		name.trim().length > 0 && shape.trim().length > 0 && logicalSortValid
	);

	function openNew() {
		editing = null;
		name = '';
		shape = '';
		logicalSort = '';
		parts = [];
		open = true;
	}
	function openEdit(l: LineType) {
		editing = l;
		name = l.name;
		shape = l.shape;
		logicalSort = l.logical_sort ?? '';
		parts = l.parts.map((p) => ({ name: p.name, regex: p.regex }));
		open = true;
	}

	async function save() {
		if (!canSave || saving) return;
		saving = true;
		const item = editing;
		const payload = {
			name: name.trim(),
			shape: shape.trim(),
			logical_sort: logicalSort || null,
			parts: parts
				.filter((p) => p.name.trim() && p.regex.trim())
				.map((p) => ({ name: p.name.trim(), regex: p.regex.trim() }))
		};
		const ok = await runMutation(
			() =>
				item
					? api.parts.lineTypes.update(systemId, item.id, payload)
					: api.parts.lineTypes.create(systemId, payload),
			item ? 'Line type updated.' : 'Line type added.'
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
			() => api.parts.lineTypes.remove(systemId, editing!.id),
			'Line type deleted.'
		);
		saving = false;
		if (ok) {
			open = false;
			await onChanged();
		}
	}

	function addPart() {
		parts = [...parts, { name: '', regex: '' }];
	}
	function removePart(part: LinePartInput) {
		parts = parts.filter((p) => p !== part);
	}
</script>

<!-- The backend allows a single line type per system. -->
<PartSection
	title="Line type"
	addLabel="Add line type"
	canAdd={lines.length === 0}
	items={lines}
	emptyMessage="No line type yet — this defines the shape of each proof line."
	onAdd={openNew}
	onEdit={openEdit}
	onReorder={() => {}}
	busy={saving}
>
	{#snippet row(l)}
		<div class="min-w-0 text-sm">
			<span class="font-medium">{l.name}</span>
			<span class="ml-2 font-mono text-xs text-muted-foreground">{l.shape}</span>
		</div>
	{/snippet}
</PartSection>

<EditSheet
	{open}
	onOpenChange={(o) => (open = o)}
	title={editing ? 'Edit line type' : 'Add line type'}
	onSave={save}
	onDelete={editing ? del : undefined}
	{saving}
	{canSave}
>
	<FormField label="Name" id="line-name" bind:value={name} placeholder="e.g. statement" maxlength={128} />
	<div class="space-y-2">
		<Label for="line-shape">Shape</Label>
		<Input id="line-shape" bind:value={shape} class="font-mono" placeholder="e.g. <formula> [<reference>]" maxlength={256} />
	</div>
	<div class="space-y-2">
		<Label for="line-logical">Logical sort <span class="text-muted-foreground">(optional)</span></Label>
		<select
			id="line-logical"
			bind:value={logicalSort}
			class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
		>
			<option value="">— none —</option>
			{#each sortNames as s (s)}
				<option value={s}>{s}</option>
			{/each}
		</select>
	</div>
	<div class="space-y-2">
		<Label>Parts <span class="text-muted-foreground">(named sub-patterns in the shape)</span></Label>
		{#each parts as part (part)}
			<div class="flex items-center gap-2">
				<Input bind:value={part.name} class="font-mono" placeholder="name" maxlength={128} />
				<span class="text-muted-foreground">matches</span>
				<Input bind:value={part.regex} class="font-mono" placeholder="regex" maxlength={512} />
				<Button type="button" variant="ghost" size="icon" class="shrink-0" onclick={() => removePart(part)}>
					<X class="size-4" /><span class="sr-only">Remove part</span>
				</Button>
			</div>
		{/each}
		<Button type="button" variant="outline" size="sm" onclick={addPart}>
			<Plus class="size-4" /> Add part
		</Button>
	</div>
</EditSheet>
