<script lang="ts">
	import { Input } from '$lib/components/ui/input';
	import { Button } from '$lib/components/ui/button';
	import RepeatableRows from '$lib/components/RepeatableRows.svelte';
	import { blankSlot, type SlotRow } from './slots';

	// A production's slots, and — unlike a rule's or a definition's metavariables —
	// which of them *bind*, and over what. A slot scopes over its siblings: the `x`
	// of `∀x.phi` over `phi`. Nothing about the template says so, which is why it is
	// declared here.
	//
	// A target is held as the sibling row's editor-local id, not its name, so that
	// renaming a slot carries the declaration with it rather than silently dropping
	// it. Names are resolved on the way in and out (see ./slots.ts).
	let {
		slots = $bindable([])
	}: {
		slots?: SlotRow[];
	} = $props();

	// A slot with no name cannot be named as a target, and nothing scopes over
	// itself — the backend rejects both, and there is no reading of either.
	function targetsFor(slot: SlotRow) {
		return slots.filter((other) => other !== slot && other.var.trim().length > 0);
	}

	function toggle(slot: SlotRow, target: SlotRow) {
		slot.scopes = slot.scopes.includes(target.id)
			? slot.scopes.filter((id) => id !== target.id)
			: [...slot.scopes, target.id];
	}
</script>

<RepeatableRows
	bind:items={slots}
	label="Slots"
	hint="(optional)"
	addLabel="Add slot"
	removeLabel="Remove slot"
	blank={blankSlot}
>
	{#snippet row(slot)}
		<Input bind:value={slot.var} placeholder="var" class="font-mono" />
		<span class="text-muted-foreground">:</span>
		<Input bind:value={slot.sort} placeholder="sort" class="font-mono" />
	{/snippet}

	{#snippet sub(slot)}
		{@const targets = targetsFor(slot)}
		{#if targets.length > 0}
			<div class="flex flex-wrap items-center gap-1 pl-1 text-xs">
				<span class="text-muted-foreground">binds over</span>
				{#each targets as target (target.id)}
					<Button
						type="button"
						size="sm"
						class="h-6 px-2 font-mono text-xs"
						aria-pressed={slot.scopes.includes(target.id)}
						variant={slot.scopes.includes(target.id) ? 'default' : 'outline'}
						onclick={() => toggle(slot, target)}
					>
						<!-- Prefixed rather than aria-labelled: an aria-label would replace
						     the slot name, and the name is the whole content here. -->
						<span class="sr-only">
							{slot.var.trim() || 'this slot'} binds over
						</span>
						{target.var}
					</Button>
				{/each}
			</div>
		{/if}
	{/snippet}
</RepeatableRows>

<p class="text-xs text-muted-foreground">
	A slot that <em>binds</em> names the siblings its binding reaches into — the
	<span class="font-mono">x</span> of <span class="font-mono">∀x.phi</span> binds over
	<span class="font-mono">phi</span>. Declaring it lets a definition's bound variables
	be read off the grammar instead of written by hand, and lets the build catch a
	bindable token wrongly marked a constant. Leave it alone for an ordinary argument
	slot; a grammar that declares none behaves exactly as before.
</p>
