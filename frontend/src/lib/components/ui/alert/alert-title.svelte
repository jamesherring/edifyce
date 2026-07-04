<script lang="ts">
	import type { HTMLAttributes } from 'svelte/elements';
	import type { Snippet } from 'svelte';
	import { cn } from '$lib/utils';

	let {
		class: className,
		children,
		...restProps
	}: HTMLAttributes<HTMLDivElement> & { children?: Snippet } = $props();
</script>

<div
	data-slot="alert-title"
	class={cn('col-start-2 min-h-4 font-medium tracking-tight', className)}
	{...restProps}
>
	{@render children?.()}
</div>
