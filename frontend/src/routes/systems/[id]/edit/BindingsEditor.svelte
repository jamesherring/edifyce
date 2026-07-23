<script lang="ts">
	import { Input } from '$lib/components/ui/input';
	import RepeatableRows from './RepeatableRows.svelte';
	import type { Binding } from '$lib/api';

	let {
		bindings = $bindable([]),
		label = 'Bindings',
		hint = '(optional)',
		description,
		addLabel = 'Add binding',
		removeLabel = 'Remove binding'
	}: {
		bindings?: Binding[];
		label?: string;
		hint?: string;
		description?: string;
		addLabel?: string;
		removeLabel?: string;
	} = $props();
</script>

<RepeatableRows
	bind:items={bindings}
	{label}
	{hint}
	{description}
	{addLabel}
	{removeLabel}
	blank={() => ({ var: '', sort: '' })}
>
	{#snippet row(binding)}
		<Input bind:value={binding.var} placeholder="var" class="font-mono" />
		<span class="text-muted-foreground">:</span>
		<Input bind:value={binding.sort} placeholder="sort" class="font-mono" />
	{/snippet}
</RepeatableRows>
