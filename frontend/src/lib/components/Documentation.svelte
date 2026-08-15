<script lang="ts">
	import { renderProse, referenceHref } from '$lib/prose';
	import type { LabelClaim, LabelDescription } from '$lib/api';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import Lock from '@lucide/svelte/icons/lock';

	let {
		documentation,
		systemId = null
	}: { documentation: LabelDescription; systemId?: string | null } = $props();

	const segments = $derived(renderProse(documentation));
	// The head of the list is what a reader follows; the rest is a count. See
	// `MENTION_LIMIT` in `app/routers/_documentation.py` on why it is capped —
	// set.mm points at `ax-13` from 656 statements.
	const hidden = $derived(documentation.mentioned_by_total - documentation.mentioned_by.length);

	// The `$j` claims, gathered by kind and kept in the order the file wrote them.
	// A Map preserves insertion order, so the first kind seen leads.
	const grouped = $derived.by(() => {
		const byKind = new Map<string, LabelClaim[]>();
		for (const claim of documentation.claims) {
			const found = byKind.get(claim.kind);
			if (found) found.push(claim);
			else byKind.set(claim.kind, [claim]);
		}
		return [...byKind];
	});

	// The kinds worth a sentence rather than a label. Everything else falls back
	// to the file's own word with its underscores opened out, deliberately: the
	// vocabulary is Metamath's and is open, so a kind this does not know must
	// still render as something a reader can look up.
	// A Map rather than an object literal: the `$j` vocabulary is open, so a kind
	// could be spelled `constructor` or `valueOf` — and a plain lookup would then
	// return an `Object.prototype` member and render function source (found in
	// review).
	const HEADINGS = new Map<string, string>([
		['usage_avoids', 'Proved without'],
		['restatement_of', 'Restatement of'],
		['justification_for', 'Justification for'],
		['definition_for', 'Definition for'],
		['equality_from', 'Equality from'],
		['notfree_from', 'Not-free from'],
		['primitive', 'Primitive'],
		['congruence', 'Congruence'],
		['bound', 'Bound']
	]);

	function claimHeading(kind: string): string {
		const known = HEADINGS.get(kind);
		if (known) return known;
		const opened = kind.replace(/_/g, ' ');
		return opened.charAt(0).toUpperCase() + opened.slice(1);
	}
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
			{#if segment.kind === 'text'}{segment.text}{:else if segment.kind === 'citation'}
				<!-- Where the prose points *outside* the corpus. The key indexes a
				     bibliography that lives in a separate file, so there is no work to
				     open — what there is is the rest of this library that came from the
				     same book, which is what the link goes to.
				     Rendered from the *span*, not rebuilt from the key and page: 103 of
				     set.mm's citations put a comma before the `p.` and a reconstruction
				     silently drops it. -->
				{#if systemId}
					<a
						href={`/systems/${systemId}/works/${encodeURIComponent(segment.citation.work)}`}
						class="text-[0.9em] underline decoration-dotted underline-offset-2 hover:decoration-solid"
						title={`Other statements from ${segment.citation.work}`}
						>{segment.text}</a
					>
				{:else}
					<span class="text-[0.9em] text-muted-foreground"
						>{segment.text}</span
					>
				{/if}
			{:else if segment.kind === 'reference'}
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

{#if grouped.length > 0}
	<div class="border-t pt-3">
		<!-- What the corpus's `$j` markup asserts about this label. Grouped by kind
		     because the kinds are unrelated claims that happen to share a shape: a
		     proof that does without `ax-12` and a statement that restates `axsep`
		     belong under different headings, not in one list. -->
		<dl class="flex flex-col gap-2">
			{#each grouped as [kind, claims] (kind)}
				<div>
					<dt class="mb-1.5 text-xs font-medium text-muted-foreground">
						{claimHeading(kind)}
					</dt>
					<dd class="flex flex-wrap items-center gap-x-2 gap-y-1">
						{#each claims as claim, i (i)}
							{#if claim.object === null}
								<!-- A directive with no preposition claims about the subject
								     alone: `primitive 'wn';` names nothing else. The heading
								     is the whole of it. -->
								<span class="text-xs text-muted-foreground">declared</span>
							{:else if claim.object_proof_id}
								<a
									href={`/proofs/${claim.object_proof_id}`}
									class="font-mono text-xs underline decoration-dotted underline-offset-2 hover:decoration-solid"
									title={claim.object_title ?? undefined}>{claim.object}</a
								>
							{:else}
								<!-- Named, but with no page to open: an axiom or a definition
								     is claimed about and was never proved. -->
								<code class="rounded bg-muted px-1 py-0.5 font-mono text-xs"
									>{claim.object}</code
								>
							{/if}
						{/each}
					</dd>
				</div>
			{/each}
		</dl>
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
