<script lang="ts">
	import { Input } from '$lib/components/ui/input';
	import RepeatableRows from './RepeatableRows.svelte';
	import type { Binding } from '$lib/api';

	let { bindings = $bindable([]), label = 'Bindings' }: { bindings?: Binding[]; label?: string } =
		$props();
</script>

<RepeatableRows
	bind:items={bindings}
	{label}
	hint="(optional)"
	addLabel="Add binding"
	removeLabel="Remove binding"
	blank={() => ({ var: '', sort: '' })}
>
	{#snippet row(binding)}
		<Input bind:value={binding.var} placeholder="var" class="font-mono" />
		<span class="text-muted-foreground">:</span>
		<Input bind:value={binding.sort} placeholder="sort" class="font-mono" />
	{/snippet}
</RepeatableRows>
