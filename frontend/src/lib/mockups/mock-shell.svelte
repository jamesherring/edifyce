<script lang="ts">
	import type { Snippet } from 'svelte';
	import MockHeader from './mock-header.svelte';
	import MockFooter from './mock-footer.svelte';
	import MotifBg from './motif-bg.svelte';
	import { DESIGNS, designStyle, type DesignKey } from './designs';

	let { design, children }: { design: DesignKey; children: Snippet } = $props();

	const d = $derived(DESIGNS[design]);
	const base = $derived(`/${design}`);
</script>

<div
	class="text-foreground relative flex min-h-screen flex-col"
	style="{designStyle(d)};background:var(--background)"
>
	<MotifBg kind={d.motif} />
	<div class="relative z-10 flex min-h-screen flex-col">
		<MockHeader {base} />
		<main class="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
			{@render children()}
		</main>
		<MockFooter />
	</div>
</div>
