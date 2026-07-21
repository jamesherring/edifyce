<script lang="ts" module>
	export type SystemStatus = 'published' | 'draft';
</script>

<script lang="ts">
	import { cn } from '$lib/utils';

	type Props = {
		status: SystemStatus;
		showDot?: boolean;
		class?: string;
	};

	let { status, showDot = true, class: className }: Props = $props();

	// Published is public (success/green); draft is private to its owner (muted).
	const config = $derived(
		status === 'published'
			? { dot: 'bg-success', text: 'text-success', label: 'PUBLISHED' }
			: { dot: 'bg-muted-foreground', text: 'text-muted-foreground', label: 'DRAFT' }
	);
</script>

<span class={cn('inline-flex items-center gap-2 font-mono text-xs', className)}>
	{#if showDot}
		<span class={cn('h-1.5 w-1.5 rounded-full', config.dot)}></span>
	{/if}
	<span class={config.text}>{config.label}</span>
</span>
