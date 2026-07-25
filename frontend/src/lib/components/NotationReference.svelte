<script lang="ts">
	import type { NotationGroup } from '$lib/notation';
	import { cn } from '$lib/utils';
	import BookOpen from '@lucide/svelte/icons/book-open';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';

	type Props = {
		groups: NotationGroup[];
		/** Whether the reference is showing. Collapsed by default: the form is what
		 *  the author came for, and the grammar is a lookup they reach for only when
		 *  a name escapes them. Bindable so a host with limited room can keep only
		 *  one authoring aid open at a time. */
		open?: boolean;
		class?: string;
	};

	let { groups, open = $bindable(false), class: className }: Props = $props();

	const count = $derived(groups.reduce((n, group) => n + group.entries.length, 0));
</script>

{#if count > 0}
	<div class={cn('flex flex-col gap-2', className)}>
		<button
			type="button"
			aria-expanded={open}
			class="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex h-8 w-fit items-center gap-1 rounded-md text-xs focus-visible:ring-2 focus-visible:outline-none"
			onclick={() => (open = !open)}
		>
			<BookOpen class="size-3.5" />
			Notation reference
			<ChevronDown class={cn('size-3.5 transition-transform', open && 'rotate-180')} />
		</button>

		{#if open}
			<!-- Capped and scrolled: a mature system's grammar is long, and the form
			     below has to stay reachable. -->
			<div
				class="bg-muted/30 flex max-h-40 flex-col gap-3 overflow-y-auto rounded-md border p-3 sm:max-h-56"
			>
				{#each groups as group (group.title)}
					<div class="flex flex-col gap-1">
						<p class="text-muted-foreground text-xs font-medium">{group.title}</p>
						<ul class="flex flex-col gap-0.5">
							{#each group.entries as entry, i (`${entry.form}-${i}`)}
								<li class="flex items-baseline justify-between gap-3 text-xs">
									<code class="min-w-0 font-mono break-words">{entry.form}</code>
									{#if entry.detail}
										<span class="text-muted-foreground shrink-0">{entry.detail}</span>
									{/if}
								</li>
							{/each}
						</ul>
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/if}
