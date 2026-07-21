<script lang="ts">
	import { Input } from '$lib/components/ui/input';
	import { Button } from '$lib/components/ui/button';
	import { Label } from '$lib/components/ui/label';
	import X from '@lucide/svelte/icons/x';
	import Plus from '@lucide/svelte/icons/plus';
	import type { Binding } from '$lib/api';

	let { bindings = $bindable([]), label = 'Bindings' }: { bindings?: Binding[]; label?: string } =
		$props();

	function add() {
		bindings = [...bindings, { var: '', sort: '' }];
	}

	function remove(i: number) {
		bindings = bindings.filter((_, idx) => idx !== i);
	}
</script>

<div class="space-y-2">
	<Label>{label} <span class="text-muted-foreground">(optional)</span></Label>
	{#each bindings as _binding, i (i)}
		<div class="flex items-center gap-2">
			<Input bind:value={bindings[i].var} placeholder="var" class="font-mono" />
			<span class="text-muted-foreground">:</span>
			<Input bind:value={bindings[i].sort} placeholder="sort" class="font-mono" />
			<Button type="button" variant="ghost" size="icon" class="shrink-0" onclick={() => remove(i)}>
				<X class="size-4" />
				<span class="sr-only">Remove binding</span>
			</Button>
		</div>
	{/each}
	<Button type="button" variant="outline" size="sm" onclick={add}>
		<Plus class="size-4" /> Add binding
	</Button>
</div>
