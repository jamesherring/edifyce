<script lang="ts">
	import { page } from '$app/state';
	import { Button } from '$lib/components/ui/button';
	import { theme } from '$lib/theme.svelte';
	import Sun from '@lucide/svelte/icons/sun';
	import Moon from '@lucide/svelte/icons/moon';
	import Turnstile from '$lib/components/icons/turnstile.svelte';

	const nav = [
		{ href: '/', label: 'Home' },
		{ href: '/compile', label: 'Compile' },
		{ href: '/verify', label: 'Verify' }
	];

	function isActive(href: string) {
		return href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
	}
</script>

<header
	class="bg-background/80 sticky top-0 z-40 w-full border-b backdrop-blur supports-[backdrop-filter]:bg-background/60"
>
	<div class="mx-auto flex h-14 max-w-5xl items-center gap-4 px-4">
		<a href="/" class="flex items-center gap-2 font-semibold">
			<span class="bg-primary text-primary-foreground grid size-7 place-items-center rounded-md">
				<Turnstile class="size-4" />
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

		<div class="ml-auto flex items-center gap-2">
			<Button variant="ghost" size="icon" onclick={() => theme.toggle()} title="Toggle theme">
				{#if theme.value === 'dark'}
					<Sun class="size-4" />
				{:else}
					<Moon class="size-4" />
				{/if}
			</Button>
		</div>
	</div>
</header>
