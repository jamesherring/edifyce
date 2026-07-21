<script lang="ts">
	import type { SVGAttributes } from 'svelte/elements';

	// Google "G" — the four brand colors are intrinsic to the logo, so unlike the
	// currentColor icons this keeps fixed fills. Sized via `size` / `class`.
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
	class={className}
	aria-hidden="true"
	{...rest}
>
	<path
		fill="#4285F4"
		d="M23.52 12.273c0-.851-.076-1.67-.218-2.455H12v4.642h6.458a5.52 5.52 0 0 1-2.394 3.622v3.01h3.878c2.269-2.089 3.578-5.166 3.578-8.819z"
	/>
	<path
		fill="#34A853"
		d="M12 24c3.24 0 5.956-1.075 7.942-2.908l-3.878-3.01c-1.075.72-2.45 1.145-4.064 1.145-3.125 0-5.77-2.111-6.714-4.948H1.276v3.108A11.996 11.996 0 0 0 12 24z"
	/>
	<path
		fill="#FBBC05"
		d="M5.286 14.279A7.212 7.212 0 0 1 4.91 12c0-.79.136-1.558.376-2.279V6.613H1.276A11.996 11.996 0 0 0 0 12c0 1.936.464 3.769 1.276 5.387l4.01-3.108z"
	/>
	<path
		fill="#EA4335"
		d="M12 4.773c1.762 0 3.343.606 4.586 1.795l3.44-3.44C17.951 1.19 15.235 0 12 0 7.31 0 3.256 2.69 1.276 6.613l4.01 3.108C6.23 6.884 8.875 4.773 12 4.773z"
	/>
</svg>
