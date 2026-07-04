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
	data-slot="alert-description"
	class={cn('text-muted-foreground col-start-2 grid justify-items-start gap-1 text-sm', className)}
	{...restProps}
>
	{@render children?.()}
</div>
