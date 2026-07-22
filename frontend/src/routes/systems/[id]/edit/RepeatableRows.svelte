<script lang="ts" generics="T">
	import { Button } from '$lib/components/ui/button';
	import { Label } from '$lib/components/ui/label';
	import X from '@lucide/svelte/icons/x';
	import Plus from '@lucide/svelte/icons/plus';
	import type { Snippet } from 'svelte';

	// A labelled, add/remove list of repeated rows (bindings, line parts,
	// antecedents, provisos). Each row's fields are supplied by the `row` snippet;
	// this owns the add/remove buttons and the flex layout. Rows are keyed by
	// object identity, so `blank()` must return a fresh object and callers wrap
	// bare strings in a `{ value }` row.
	let {
		items = $bindable(),
		label,
		hint,
		addLabel,
		removeLabel,
		blank,
		row
	}: {
		items: T[];
		label: string;
		hint?: string;
		addLabel: string;
		removeLabel: string;
		blank: () => T;
		row: Snippet<[T]>;
	} = $props();

	function add() {
		items = [...items, blank()];
	}
	function remove(item: T) {
		items = items.filter((i) => i !== item);
	}
</script>

<div class="space-y-2">
	<Label>{label}{#if hint}&nbsp;<span class="text-muted-foreground">{hint}</span>{/if}</Label>
	<!-- Keyed by object identity so removing a middle row can't shift focus/caret
	     onto the wrong row. -->
	{#each items as item (item)}
		<div class="flex items-center gap-2">
			{@render row(item)}
			<Button type="button" variant="ghost" size="icon" class="shrink-0" onclick={() => remove(item)}>
				<X class="size-4" /><span class="sr-only">{removeLabel}</span>
			</Button>
		</div>
	{/each}
	<Button type="button" variant="outline" size="sm" onclick={add}>
		<Plus class="size-4" /> {addLabel}
	</Button>
</div>
