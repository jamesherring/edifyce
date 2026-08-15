<script lang="ts">
	import { cn } from '$lib/utils';
	import type { Snippet } from 'svelte';

	type Props = {
		title: string;
		description?: string;
		size?: 'default' | 'display';
		spacing?: 'default' | 'lg';
		actions?: Snippet;
		class?: string;
	};

	let {
		title,
		description,
		size = 'default',
		spacing = 'default',
		actions,
		class: className
	}: Props = $props();
</script>

<div
	class={cn(
		'flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between',
		spacing === 'lg' ? 'mb-8' : 'mb-6',
		className
	)}
>
	<div class="min-w-0">
		<!-- Edifyce's body face is already the CMU serif; display is just a larger,
		     lighter cut of it rather than a separate display font. -->
		<h1
			class={cn(
				'truncate tracking-tight',
				size === 'display' ? 'text-3xl font-normal' : 'text-2xl font-semibold'
			)}
		>
			{title}
		</h1>
		{#if description}
			<p class="mt-1 text-sm text-muted-foreground">{description}</p>
		{/if}
	</div>
	{#if actions}
		<div class="shrink-0">
			{@render actions()}
		</div>
	{/if}
</div>
