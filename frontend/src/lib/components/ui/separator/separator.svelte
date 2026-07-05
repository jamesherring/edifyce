<script lang="ts">
	import type { HTMLAttributes } from 'svelte/elements';
	import { cn } from '$lib/utils';

	let {
		class: className,
		orientation = 'horizontal',
		...restProps
	}: HTMLAttributes<HTMLDivElement> & { orientation?: 'horizontal' | 'vertical' } = $props();
</script>

<div
	role="separator"
	aria-orientation={orientation}
	class={cn(
		'bg-border shrink-0',
		orientation === 'horizontal' ? 'h-px w-full' : 'h-full w-px',
		className
	)}
	{...restProps}
></div>
