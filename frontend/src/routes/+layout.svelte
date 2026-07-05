<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import favicon from '$lib/assets/favicon.svg';
	import SiteHeader from '$lib/components/site-header.svelte';
	import { theme } from '$lib/theme.svelte';

	let { children } = $props();

	onMount(() => theme.init());
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>Edifyce — Human-Readable, Computer-Verifiable Mathematics</title>
</svelte:head>

<div class="flex min-h-screen flex-col">
	<SiteHeader />
	<main class="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
		{@render children()}
	</main>
	<footer class="text-muted-foreground border-t py-6 text-center text-sm">
		Edifyce · a formal proof assistant
	</footer>
</div>
