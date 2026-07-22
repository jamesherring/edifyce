<script lang="ts" generics="T extends { id: string }">
	import SectionCard from '$lib/components/SectionCard.svelte';
	import InlineEmpty from '$lib/components/InlineEmpty.svelte';
	import { Button } from '$lib/components/ui/button';
	import type { Snippet } from 'svelte';
	import Plus from '@lucide/svelte/icons/plus';
	import Pencil from '@lucide/svelte/icons/pencil';
	import ChevronUp from '@lucide/svelte/icons/chevron-up';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';

	type Props = {
		title: string;
		addLabel?: string;
		canAdd?: boolean;
		items: T[];
		emptyMessage: string;
		row: Snippet<[T]>;
		onAdd: () => void;
		onEdit: (item: T) => void;
		onReorder: (ids: string[]) => void;
		busy?: boolean;
	};

	let {
		title,
		addLabel = 'Add',
		canAdd = true,
		items,
		emptyMessage,
		row,
		onAdd,
		onEdit,
		onReorder,
		busy = false
	}: Props = $props();

	function move(i: number, dir: -1 | 1) {
		const j = i + dir;
		if (j < 0 || j >= items.length) return;
		const ids = items.map((it) => it.id);
		[ids[i], ids[j]] = [ids[j], ids[i]];
		onReorder(ids);
	}
</script>

<SectionCard>
	<div class="mb-3 flex items-center justify-between gap-2">
		<h2 class="text-sm font-medium">{title}</h2>
		{#if canAdd}
			<Button type="button" variant="outline" size="sm" onclick={onAdd} disabled={busy}>
				<Plus class="size-4" /> {addLabel}
			</Button>
		{/if}
	</div>
	{#if items.length === 0}
		<InlineEmpty message={emptyMessage} />
	{:else}
		<ul class="divide-y">
			{#each items as item, i (item.id)}
				<li class="flex items-center gap-3 py-2">
					<div class="min-w-0 flex-1">{@render row(item)}</div>
					<div class="flex shrink-0 items-center gap-0.5">
						<Button
							type="button"
							variant="ghost"
							size="icon"
							class="size-8"
							disabled={busy || i === 0}
							onclick={() => move(i, -1)}
						>
							<ChevronUp class="size-4" /><span class="sr-only">Move up</span>
						</Button>
						<Button
							type="button"
							variant="ghost"
							size="icon"
							class="size-8"
							disabled={busy || i === items.length - 1}
							onclick={() => move(i, 1)}
						>
							<ChevronDown class="size-4" /><span class="sr-only">Move down</span>
						</Button>
						<Button
							type="button"
							variant="ghost"
							size="icon"
							class="size-8"
							disabled={busy}
							onclick={() => onEdit(item)}
						>
							<Pencil class="size-4" /><span class="sr-only">Edit</span>
						</Button>
					</div>
				</li>
			{/each}
		</ul>
	{/if}
</SectionCard>
