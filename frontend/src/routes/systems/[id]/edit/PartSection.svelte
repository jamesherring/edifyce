<script lang="ts" generics="T extends { id: string }">
	import SectionCard from '$lib/components/SectionCard.svelte';
	import InlineEmpty from '$lib/components/InlineEmpty.svelte';
	import { Button } from '$lib/components/ui/button';
	import type { Snippet } from 'svelte';
	import Plus from '@lucide/svelte/icons/plus';
	import Pencil from '@lucide/svelte/icons/pencil';
	import GripVertical from '@lucide/svelte/icons/grip-vertical';
	import ChevronUp from '@lucide/svelte/icons/chevron-up';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';

	type Props = {
		title: string;
		/** Anchor target, so the outline can link to this section. */
		id?: string;
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
		id,
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

	/** Row being dragged, and the row it would land on. */
	let from = $state<number | null>(null);
	let over = $state<number | null>(null);
	// Only a drag started on the grip counts: rows carry formulas worth selecting,
	// and a permanently draggable <li> can't be selected at all.
	let armed = $state(false);

	function reorderTo(to: number) {
		// `busy` can flip mid-drag when an earlier reorder is still in flight; the
		// indices this drag started from are stale by then, so drop it. (The
		// `draggable` attribute stops the drag starting, but not one already begun.)
		if (busy || from === null || to === from) return;
		const ids = items.map((item) => item.id);
		const [moved] = ids.splice(from, 1);
		ids.splice(to, 0, moved);
		onReorder(ids);
	}

	/** Swap with a neighbour — what the chevrons do, and the keyboard path. */
	function move(i: number, dir: -1 | 1) {
		const j = i + dir;
		if (j < 0 || j >= items.length) return;
		const ids = items.map((item) => item.id);
		[ids[i], ids[j]] = [ids[j], ids[i]];
		onReorder(ids);
	}

	function endDrag() {
		from = null;
		over = null;
		armed = false;
	}
</script>

<SectionCard {id} class="scroll-mt-20">
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
				<li
					draggable={armed && !busy}
					class={[
						'flex items-center gap-3 py-2',
						from === i && 'opacity-40',
						// Mark the edge the row would drop against, so the landing spot shows.
						over === i && from !== null && from > i && 'border-primary border-t-2',
						over === i && from !== null && from < i && 'border-primary border-b-2'
					]}
					ondragstart={(e) => {
						if (busy) return;
						from = i;
						if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
					}}
					ondragover={(e) => {
						if (from === null) return;
						e.preventDefault();
						over = i;
					}}
					ondrop={(e) => {
						e.preventDefault();
						reorderTo(i);
						endDrag();
					}}
					ondragend={endDrag}
				>
					<!-- Mouse-only affordance: the chevrons below are the keyboard path, so
					     this stays out of the tab order and the accessibility tree. -->
					<span
						aria-hidden="true"
						title="Drag to reorder"
						class={[
							'text-muted-foreground/50 hover:text-muted-foreground shrink-0 touch-none',
							busy ? 'cursor-not-allowed' : 'cursor-grab active:cursor-grabbing'
						]}
						onpointerdown={() => (armed = !busy)}
						onpointerup={() => (armed = false)}
						onpointercancel={() => (armed = false)}
					>
						<GripVertical class="size-4" />
					</span>
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
