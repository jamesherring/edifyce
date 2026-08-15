<script lang="ts">
	// KaTeX's stylesheet ships the fonts it sets with, so it is imported beside
	// the one component that renders its markup rather than in `app.css`: nothing
	// else on the site is mathematics.
	import 'katex/dist/katex.min.css';
	import { typeset } from '$lib/math';

	type Props = {
		/** The TeX source to set. */
		tex: string;
		class?: string;
	};

	let { tex, class: className }: Props = $props();

	const html = $derived(typeset(tex));
</script>

{#if html}
	<!-- KaTeX escapes its input and `trust` is off, so this cannot emit markup a
	     stored notation template smuggled in. -->
	<span class={className}>{@html html}</span>
{:else}
	<!-- Unparseable TeX: show the source it would have been set from, which is at
	     least readable, rather than KaTeX's red error over the whole line. -->
	<span class={['font-mono', className]}>{tex}</span>
{/if}
