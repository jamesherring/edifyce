<script lang="ts">
	import type { SVGAttributes } from 'svelte/elements';

	// Turnstile (⊢) mark in the lucide house style — currentColor stroke on a
	// 24×24 grid — so it drops into the same slots as the @lucide/svelte icons
	// and inherits text color / `size-*` classes.
	let {
		size = 24,
		class: className,
		...rest
	}: { size?: number; class?: string } & SVGAttributes<SVGSVGElement> = $props();
</script>

<svg
	xmlns="http://www.w3.org/2000/svg"
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width="2"
	stroke-linecap="round"
	stroke-linejoin="round"
	class={className}
	{...rest}
>
	<path d="M8 5v14" />
	<path d="M8 12h9" />
</svg>
