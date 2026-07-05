<script lang="ts">
	import { page } from '$app/state';

	// TEMPORARY: a floating switcher for comparing the homepage design mockups.
	// Remove this component (and its use in the root layout) once a direction is
	// chosen. Its styling is deliberately self-contained so it looks identical on
	// every variant regardless of that variant's palette.

	const options = [
		{ key: '', label: 'Original' },
		{ key: '/1', label: '1 · Penrose' },
		{ key: '/3', label: '3 · Blackboard' },
		{ key: '/6', label: '6 · Golden' },
		{ key: '/8', label: '8 · Modular' }
	];

	// The path shared across variants: '' (home), '/compile' or '/verify'.
	const rest = $derived.by(() => {
		const path = page.url.pathname;
		const design = path.match(/^\/[1368](\/.*)?$/);
		if (design) return design[1] ?? '';
		return path === '/' ? '' : path;
	});

	const current = $derived.by(() => {
		const m = page.url.pathname.match(/^\/[1368]/);
		return m ? m[0] : '';
	});

	function target(key: string): string {
		return key + rest || '/';
	}
</script>

<div class="switcher" role="navigation" aria-label="Design variant switcher">
	<span class="cap">Design</span>
	{#each options as opt (opt.key)}
		<a
			href={target(opt.key)}
			class="chip"
			class:active={opt.key === current}
			aria-current={opt.key === current ? 'page' : undefined}
		>
			{opt.label}
		</a>
	{/each}
</div>

<style>
	.switcher {
		position: fixed;
		right: 0.75rem;
		bottom: 0.75rem;
		z-index: 60;
		display: flex;
		align-items: center;
		gap: 0.25rem;
		padding: 0.35rem 0.4rem 0.35rem 0.6rem;
		border-radius: 999px;
		background: rgba(18, 18, 22, 0.92);
		border: 1px solid rgba(255, 255, 255, 0.14);
		box-shadow: 0 8px 24px -8px rgba(0, 0, 0, 0.55);
		font-family: ui-sans-serif, system-ui, sans-serif;
		backdrop-filter: blur(6px);
		max-width: calc(100vw - 1.5rem);
		flex-wrap: wrap;
	}
	.cap {
		font-size: 0.6rem;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		color: rgba(255, 255, 255, 0.5);
		padding-right: 0.15rem;
	}
	.chip {
		font-size: 0.72rem;
		line-height: 1;
		color: rgba(255, 255, 255, 0.72);
		text-decoration: none;
		padding: 0.35rem 0.55rem;
		border-radius: 999px;
		white-space: nowrap;
		transition:
			background-color 0.15s,
			color 0.15s;
	}
	.chip:hover {
		color: #fff;
		background: rgba(255, 255, 255, 0.1);
	}
	.chip.active {
		color: #12121a;
		background: #f4f4f5;
		font-weight: 600;
	}
	.chip:focus-visible {
		outline: 2px solid #8ab4ff;
		outline-offset: 2px;
	}
	@media (max-width: 520px) {
		.cap {
			display: none;
		}
	}
</style>
