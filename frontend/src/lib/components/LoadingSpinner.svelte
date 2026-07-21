<script lang="ts">
	import type { Snippet } from 'svelte';
	import Loader2 from '@lucide/svelte/icons/loader-circle';
	import { cn } from '$lib/utils';

	type Props = {
		message?: string;
		detail?: string;
		actions?: Snippet;
		children?: Snippet;
		class?: string;
	};

	let { message, detail, actions, children, class: className }: Props = $props();
</script>

<div class={cn('flex flex-col items-center gap-3 py-12', className)}>
	<Loader2 class="h-6 w-6 animate-spin text-muted-foreground" />
	{#if message}
		<p class="text-sm text-muted-foreground">{message}</p>
	{/if}
	{#if detail}
		<p class="text-xs text-muted-foreground/60">{detail}</p>
	{/if}
	{#if actions}
		{@render actions()}
	{/if}
	{#if children}
		{@render children()}
	{/if}
</div>
