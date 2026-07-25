<script lang="ts">
	import CompileStatus from './CompileStatus.svelte';
	import type { SystemValidation } from '$lib/api';

	export interface OutlineSection {
		id: string;
		title: string;
		count: number;
	}

	type Props = {
		sections: OutlineSection[];
		validation: SystemValidation | null;
		validating: boolean;
	};

	let { sections, validation, validating }: Props = $props();

	/** Where the reading area starts: just below the sticky site header. */
	const THRESHOLD = 96;

	let current = $state<string | null>(null);
	let pinned = $state<string | null>(null);

	const active = $derived(pinned ?? current);

	// Depend on the ids alone: the section list is rebuilt whenever a count
	// changes, and rebinding listeners on every part edit is pointless.
	const sectionIds = $derived(sections.map((s) => s.id).join(','));

	$effect(() => {
		const ids = sectionIds.split(',').filter(Boolean);
		if (ids.length === 0) return;

		let frame = 0;
		// The section being read is the *last* one whose top has passed under the
		// header — not the first one still touching the viewport, which is the one
		// scrolling away. Before the first has reached it, the first is current.
		function recompute() {
			frame = 0;
			let found = ids[0];
			for (const id of ids) {
				const el = document.getElementById(id);
				if (el && el.getBoundingClientRect().top <= THRESHOLD) found = id;
			}
			// The page ends with the settings cards, so the last section or two never
			// reach the header line and could never highlight. Being at the bottom
			// means being in the last one.
			const atBottom =
				window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
			current = atBottom ? ids[ids.length - 1] : found;
		}

		function onScroll() {
			if (!frame) frame = requestAnimationFrame(recompute);
		}

		recompute();
		window.addEventListener('scroll', onScroll, { passive: true });
		window.addEventListener('resize', onScroll);
		return () => {
			if (frame) cancelAnimationFrame(frame);
			window.removeEventListener('scroll', onScroll);
			window.removeEventListener('resize', onScroll);
		};
	});

	// A click pins its target until the user scrolls for themselves. Near the end
	// of the page a jump lands short — there's nothing left to scroll — and
	// highlighting the section above the one just asked for reads as a bug.
	$effect(() => {
		if (!pinned) return;
		const release = () => (pinned = null);
		const events = ['wheel', 'touchstart', 'keydown'] as const;
		for (const type of events) window.addEventListener(type, release, { passive: true });
		return () => {
			for (const type of events) window.removeEventListener(type, release);
		};
	});
</script>

<div class="flex flex-col gap-4">
	<CompileStatus {validation} {validating} compact />

	<nav aria-label="System contents" class="flex flex-col gap-0.5 border-t pt-4">
		{#each sections as section (section.id)}
			<a
				href={`#${section.id}`}
				aria-current={active === section.id ? 'true' : undefined}
				onclick={() => (pinned = section.id)}
				class={[
					'flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-sm transition-colors',
					active === section.id
						? 'bg-accent text-accent-foreground font-medium'
						: 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
				]}
			>
				<span class="truncate">{section.title}</span>
				<span class="text-muted-foreground shrink-0 text-xs tabular-nums">{section.count}</span>
			</a>
		{/each}
	</nav>
</div>
