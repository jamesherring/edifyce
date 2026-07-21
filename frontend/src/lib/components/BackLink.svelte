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
		'inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground',
		className
	)}
>
	<ArrowLeft class="h-4 w-4" />
	{label}
</a>
