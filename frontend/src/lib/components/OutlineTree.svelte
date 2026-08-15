<script lang="ts">
	import type { Folder } from '$lib/api';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import Self from './OutlineTree.svelte';

	let {
		folders,
		/** Roots start open so the shape is visible without a click; deeper levels
		 *  start closed, since a corpus has hundreds of them. */
		open: openByDefault = false,
		/** Id of the folder currently being read, for the highlight. */
		selected = null,
		/** Given, a folder holding proofs becomes a button that asks for them.
		 *  Omitted, the tree is the read-only shape it has always been. */
		onselect
	}: {
		folders: Folder[];
		open?: boolean;
		selected?: string | null;
		onselect?: (folder: Folder) => void;
	} = $props();

	let opened = $state<Record<string, boolean>>({});

	function isOpen(folder: Folder): boolean {
		return opened[folder.id] ?? openByDefault;
	}
</script>

<ul class="flex flex-col gap-0.5">
	{#each folders as folder (folder.id)}
		<li>
			<div class="flex items-baseline gap-1.5">
				{#if folder.children.length > 0}
					<button
						type="button"
						class="shrink-0 self-center text-muted-foreground hover:text-foreground"
						aria-expanded={isOpen(folder)}
						aria-label={isOpen(folder) ? `Collapse ${folder.name}` : `Expand ${folder.name}`}
						onclick={() => (opened[folder.id] = !isOpen(folder))}
					>
						{#if isOpen(folder)}
							<ChevronDown class="size-4" />
						{:else}
							<ChevronRight class="size-4" />
						{/if}
					</button>
				{:else}
					<span class="size-4 shrink-0" aria-hidden="true"></span>
				{/if}
				{#if onselect && folder.proofs > 0}
					<button
						type="button"
						class={[
							'rounded px-1 text-left text-sm hover:underline',
							selected === folder.id && 'bg-accent font-medium text-accent-foreground'
						]}
						aria-current={selected === folder.id ? 'true' : undefined}
						onclick={() => onselect(folder)}
					>
						{folder.name}
					</button>
				{:else}
					<span class="text-sm">{folder.name}</span>
				{/if}
				{#if folder.proofs > 0}
					<span class="shrink-0 text-xs text-muted-foreground">{folder.proofs}</span>
				{/if}
			</div>
			{#if folder.description}
				<!-- Clamped, because a section's introduction can be enormous: set.mm's
				     21 part-level descriptions run to 27,820 characters between them and
				     one subsection's is 20,783 on its own. Unclamped they bury the tree
				     they are meant to annotate. `title` puts the whole of it one hover
				     away, and the folder's own page is where it belongs in full. -->
				<p
					class="ml-5.5 line-clamp-2 text-xs text-muted-foreground"
					title={folder.description}
				>
					{folder.description}
				</p>
			{/if}
			{#if folder.children.length > 0 && isOpen(folder)}
				<div class="ml-5.5 mt-0.5 border-l pl-2">
					<Self folders={folder.children} {selected} {onselect} />
				</div>
			{/if}
		</li>
	{/each}
</ul>
