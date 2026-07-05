<script lang="ts">
	import { page } from '$app/state';
	import Sigma from '@lucide/svelte/icons/sigma';

	// `base` is '' for the live site or '/1', '/3', … inside a design mockup.
	let { base = '' }: { base?: string } = $props();

	const home = $derived(base || '/');
	const nav = $derived([
		{ href: home, label: 'Home' },
		{ href: `${base}/compile`, label: 'Compile' },
		{ href: `${base}/verify`, label: 'Verify' }
	]);

	function isActive(href: string) {
		return href === home ? page.url.pathname === home : page.url.pathname === href;
	}
</script>

<header
	class="bg-background/80 sticky top-0 z-40 w-full border-b backdrop-blur supports-[backdrop-filter]:bg-background/60"
>
	<div class="mx-auto flex h-14 max-w-5xl items-center gap-4 px-4">
		<a href={home} class="flex items-center gap-2 font-semibold">
			<span class="bg-primary text-primary-foreground grid size-7 place-items-center rounded-md">
				<Sigma class="size-4" />
			</span>
			<span class="tracking-tight">Edifyce</span>
		</a>

		<nav class="ml-2 flex items-center gap-1">
			{#each nav as item (item.href)}
				<a
					href={item.href}
					class={[
						'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
						isActive(item.href)
							? 'bg-accent text-accent-foreground'
							: 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
					]}
				>
					{item.label}
				</a>
			{/each}
		</nav>
	</div>
</header>
