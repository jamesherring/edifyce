<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import favicon from '$lib/assets/favicon.svg';
	import SiteHeader from '$lib/components/site-header.svelte';
	import DesignSwitcher from '$lib/mockups/design-switcher.svelte';
	import { theme } from '$lib/theme.svelte';

	let { children } = $props();

	onMount(() => theme.init());

	// Design mockups (/1, /3, /6, /8) bring their own chrome via a nested layout,
	// so the default header/footer is skipped for them.
	const isDesign = $derived(/^\/[1368](\/|$)/.test(page.url.pathname));
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>Edifyce — Human-Readable, Computer-Verifiable Mathematics</title>
</svelte:head>

{#if isDesign}
	{@render children()}
{:else}
	<div class="flex min-h-screen flex-col">
		<SiteHeader />
		<main class="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
			{@render children()}
		</main>
		<footer class="text-muted-foreground border-t py-6 text-center text-sm">
			Edifyce · a formal proof assistant
		</footer>
	</div>
{/if}

<DesignSwitcher />
