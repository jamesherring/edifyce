<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import SiteHeader from '$lib/components/site-header.svelte';
	import PenroseBg from '$lib/components/penrose-bg.svelte';
	import { Toaster } from '$lib/components/ui/sonner';
	import { theme } from '$lib/theme.svelte';
	import { auth } from '$lib/auth.svelte';

	let { children } = $props();

	onMount(() => {
		theme.init();
		auth.init();
	});
</script>

<svelte:head>
	<link
		rel="preload"
		href="/fonts/cmu-serif-roman.woff2"
		as="font"
		type="font/woff2"
		crossorigin="anonymous"
	/>
	<title>Edifyce — Human-Readable, Computer-Verifiable Mathematics</title>
</svelte:head>

<PenroseBg />

<div class="relative z-10 flex min-h-screen flex-col">
	<SiteHeader />
	<main class="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
		{@render children()}
	</main>
	<footer class="text-muted-foreground border-t py-6 text-center text-sm">
		Edifyce · a formal proof assistant
	</footer>
</div>

<Toaster />
