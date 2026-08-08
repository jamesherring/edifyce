<script lang="ts">
	import { renderProse, referenceHref } from '$lib/prose';
	import type { LabelDescription } from '$lib/api';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import Lock from '@lucide/svelte/icons/lock';

	let { documentation }: { documentation: LabelDescription } = $props();

	const segments = $derived(renderProse(documentation));
	// The head of the list is what a reader follows; the rest is a count. See
	// `MENTION_LIMIT` in `app/routers/_documentation.py` on why it is capped —
	// set.mm points at `ax-13` from 656 statements.
	const hidden = $derived(documentation.mentioned_by_total - documentation.mentioned_by.length);
</script>

{#if documentation.discouraged_usage || documentation.discouraged_modification}
	<!-- Ahead of the prose, because both are warnings about acting on what follows
	     rather than notes about it. Lifted out of the sentences they were written
	     as, which is the whole point of storing them as flags. -->
	<ul class="flex flex-col gap-1.5">
		{#if documentation.discouraged_usage}
			<li class="flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2">
				<TriangleAlert class="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-500" />
				<span class="text-xs">
					<span class="font-medium">New usage is discouraged.</span>
					This statement stands, but the corpus asks that new work not be built on it.
				</span>
			</li>
		{/if}
		{#if documentation.discouraged_modification}
			<li class="flex items-start gap-2 rounded-md border px-3 py-2">
				<Lock class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
				<span class="text-xs">
					<span class="font-medium">Proof modification is discouraged.</span>
					This proof is written the way it is deliberately.
				</span>
			</li>
		{/if}
	</ul>
{/if}

{#if documentation.text}
	<!-- Paragraphs survive storage as blank lines, which is how a comment marks
	     them; `whitespace-pre-line` is what shows them. The `~ label` spans come
	     back from the API with the offsets they occupy, so this is a slice rather
	     than a parse (see `$lib/prose`). -->
	<p class="whitespace-pre-line text-sm leading-relaxed">
		{#each segments as segment, i (i)}
			{#if segment.kind === 'text'}{segment.text}{:else}
				{@const href = referenceHref(segment.reference)}
				{#if href}
					<a
						{href}
						class="font-mono text-[0.9em] underline decoration-dotted underline-offset-2 hover:decoration-solid"
						title={segment.reference.title ?? undefined}
						target={href.startsWith('http') ? '_blank' : undefined}
						rel={href.startsWith('http') ? 'noreferrer' : undefined}
					>{segment.reference.target}</a
					>
				{:else}
					<!-- Named, but not reachable: a definition or an axiom has no page of
					     its own yet, and a draft's id is deliberately withheld. Showing the
					     label is still better than showing the `~`. -->
					<code class="rounded bg-muted px-1 py-0.5 font-mono text-[0.9em]"
						>{segment.reference.target}</code
					>
				{/if}
			{/if}
		{/each}
	</p>
{/if}

{#if documentation.avoids.length > 0}
	<div class="border-t pt-3">
		<h3 class="mb-1.5 text-xs font-medium text-muted-foreground">Proved without</h3>
		<!-- A result about the *proof* rather than the theorem: this one is derivable
		     without those. Nowhere else to read it from — an avoided statement is
		     usually nowhere in the citation graph, that being the point. Presented as
		     the corpus's claim, since nothing here re-derives the dependencies. -->
		<ul class="flex flex-wrap items-center gap-x-2 gap-y-1">
			{#each documentation.avoids as avoided (avoided)}
				<li>
					<code class="rounded bg-muted px-1 py-0.5 font-mono text-xs">{avoided}</code>
				</li>
			{/each}
		</ul>
	</div>
{/if}

{#if documentation.mentioned_by.length > 0}
	<div class="border-t pt-3">
		<h3 class="mb-1.5 text-xs font-medium text-muted-foreground">
			Mentioned by
			<span class="tabular-nums">({documentation.mentioned_by_total})</span>
		</h3>
		<!-- The direction the file cannot answer: a statement never says what was
		     built on it. -->
		<ul class="flex flex-wrap items-center gap-x-2 gap-y-1">
			{#each documentation.mentioned_by as mention (mention.label)}
				<li>
					{#if mention.proof_id}
						<a
							href={`/proofs/${mention.proof_id}`}
							class="font-mono text-xs underline decoration-dotted underline-offset-2 hover:decoration-solid"
							title={mention.title ?? undefined}>{mention.label}</a
						>
					{:else}
						<code class="rounded bg-muted px-1 py-0.5 font-mono text-xs">{mention.label}</code>
					{/if}
				</li>
			{/each}
			{#if hidden > 0}
				<li class="text-xs text-muted-foreground">and {hidden} more</li>
			{/if}
		</ul>
	</div>
{/if}

{#if documentation.attributions.length > 0}
	<ul class="flex flex-col gap-1 border-t pt-3">
		{#each documentation.attributions as credit, i (i)}
			<li class="text-xs text-muted-foreground">
				<span class="font-medium">{credit.kind}</span> by {credit.who}, {credit.dated}
			</li>
		{/each}
	</ul>
{/if}
