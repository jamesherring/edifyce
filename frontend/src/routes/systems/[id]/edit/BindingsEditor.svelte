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

	function remove(binding: Binding) {
		bindings = bindings.filter((b) => b !== binding);
	}
</script>

<div class="space-y-2">
	<Label>{label} <span class="text-muted-foreground">(optional)</span></Label>
	<!-- Keyed by object identity so removing a middle row can't shift focus/caret
	     onto the wrong binding. -->
	{#each bindings as binding (binding)}
		<div class="flex items-center gap-2">
			<Input bind:value={binding.var} placeholder="var" class="font-mono" />
			<span class="text-muted-foreground">:</span>
			<Input bind:value={binding.sort} placeholder="sort" class="font-mono" />
			<Button type="button" variant="ghost" size="icon" class="shrink-0" onclick={() => remove(binding)}>
				<X class="size-4" />
				<span class="sr-only">Remove binding</span>
			</Button>
		</div>
	{/each}
	<Button type="button" variant="outline" size="sm" onclick={add}>
		<Plus class="size-4" /> Add binding
	</Button>
</div>
