<script lang="ts">
	import { resolve } from '$app/paths';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import { cn } from '$lib/utils';

	type Props = {
		href: string;
		label: string;
		class?: string;
	};

	let { href, label, class: className }: Props = $props();
</script>

<a
	href={resolve(href as '/')}
	class={cn(
		'text-muted-foreground hover:text-foreground -my-2 inline-flex min-h-11 items-center gap-1 py-2 text-sm transition-colors',
		className
	)}
>
	<ArrowLeft class="h-4 w-4" />
	{label}
</a>
