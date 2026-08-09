<script lang="ts">
	import type { ProofCitations, TheoremCitation } from '$lib/api';

	let { citations }: { citations: ProofCitations } = $props();

	// The head of the list is what a reader follows; the rest is a count. Capped
	// server-side (`CITATION_LIMIT` in app/routers/proofs.py) because the graph's
	// head is enormous — most of set.mm cites `ax-mp`.
	const hidden = $derived(citations.cited_by_total - citations.cited_by.length);
</script>

{#snippet entry(citation: TheoremCitation)}
	{#if citation.proof_id}
		<a
			href={`/proofs/${citation.proof_id}`}
			class="font-mono text-xs underline decoration-dotted underline-offset-2 hover:decoration-solid"
			title={citation.title ?? undefined}>{citation.label}</a
		>
	{:else}
		<!-- Cited, but with no page to open: half a corpus's labels are primitives
		     that were never proved, and a draft's id is deliberately withheld. -->
		<code class="rounded bg-muted px-1 py-0.5 font-mono text-xs">{citation.label}</code>
	{/if}
{/snippet}

{#if citations.cites.length > 0}
	<div class="border-t pt-3">
		<h3 class="mb-1.5 text-xs font-medium text-muted-foreground">
			Cites
			<span class="tabular-nums">({citations.cites.length})</span>
		</h3>
		<!-- In the order the proof first uses them, which is its own order and the
		     one a reader following it down the page expects. -->
		<ul class="flex flex-wrap items-center gap-x-2 gap-y-1">
			{#each citations.cites as citation (citation.label)}
				<li>{@render entry(citation)}</li>
			{/each}
		</ul>
	</div>
{/if}

{#if citations.cited_by.length > 0}
	<div class="border-t pt-3">
		<h3 class="mb-1.5 text-xs font-medium text-muted-foreground">
			Cited by
			<span class="tabular-nums">({citations.cited_by_total})</span>
		</h3>
		<!-- The direction the corpus cannot be read in: nothing in a `.mm` file says
		     what was built on a statement, and for a foundational one the answer is
		     most of the library. -->
		<ul class="flex flex-wrap items-center gap-x-2 gap-y-1">
			{#each citations.cited_by as citation (citation.label)}
				<li>{@render entry(citation)}</li>
			{/each}
			{#if hidden > 0}
				<li class="text-xs text-muted-foreground">and {hidden} more</li>
			{/if}
		</ul>
	</div>
{/if}
