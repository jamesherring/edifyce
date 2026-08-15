<script lang="ts">
	import type { ProofProvenance } from '$lib/api';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import CircleHelp from '@lucide/svelte/icons/circle-help';

	let { provenance }: { provenance: ProofProvenance } = $props();

	// Three separate facts, and the card appears for any of them. A proof that
	// assumes nothing but could not account for a citation is not a proof that
	// assumes nothing — see `complete` on the API model.
	const incomplete = $derived(
		provenance.unresolved.length > 0 || provenance.unread_lemmas.length > 0
	);
</script>

{#if provenance.assumes.length > 0}
	<div class="flex flex-col gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2">
		<div class="flex items-start gap-2">
			<TriangleAlert class="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-500" />
			<p class="text-xs">
				<span class="font-medium">
					This proof is conditional on {provenance.assumes.length}
					{provenance.assumes.length === 1 ? 'assumption' : 'assumptions'}.
				</span>
				It is a complete proof of an implication: everything below is taken on without a
				proof of its own.
			</p>
		</div>
		<ul class="flex flex-col gap-2 pl-6">
			{#each provenance.assumes as assumed (assumed.theorem_id)}
				<li class="flex flex-col gap-0.5">
					<a
						href={`/systems/${assumed.formal_system_id}/assumptions/${encodeURIComponent(assumed.label)}`}
						class="font-mono text-xs underline decoration-dotted underline-offset-2 hover:decoration-solid"
						>{assumed.label}</a
					>
					<code class="whitespace-pre-wrap break-words font-mono text-xs text-muted-foreground"
						>{assumed.statement}</code
					>
					<p class="text-xs text-muted-foreground">
						{assumed.reason}{#if assumed.source}
							— <span class="italic">{assumed.source}</span>{/if}
					</p>
				</li>
			{/each}
		</ul>
	</div>
{/if}

{#if incomplete}
	<!-- The honest half. A report that quietly dropped what it could not account
	     for would read as a short list rather than an incomplete one, which is the
	     one failure this surface exists to prevent. -->
	<div class="flex items-start gap-2 rounded-md border px-3 py-2">
		<CircleHelp class="mt-0.5 size-4 shrink-0 text-muted-foreground" />
		<!-- Unkeyed on purpose: a lemma is named by `proofs.name`, which carries no
		     unique constraint, so a keyed list would throw on two lemmas sharing a
		     name rather than list them twice. -->
		<div class="flex flex-col gap-1 text-xs">
			<span class="font-medium">This report is incomplete.</span>
			{#if provenance.unresolved.length > 0}
				<p class="text-muted-foreground">
					Cited but not accounted for — no library entry, inference rule or hypothesis
					answers to
					{#each provenance.unresolved as label, i}<code
							class="rounded bg-muted px-1 py-0.5 font-mono">{label}</code
						>{#if i < provenance.unresolved.length - 1},
						{/if}{/each}.
				</p>
			{/if}
			{#if provenance.unread_lemmas.length > 0}
				<p class="text-muted-foreground">
					These lemma proofs hold no stored structure, so their own assumptions could not
					be read —
					{#each provenance.unread_lemmas as name, i}<code
							class="rounded bg-muted px-1 py-0.5 font-mono">{name}</code
						>{#if i < provenance.unread_lemmas.length - 1},
						{/if}{/each}. Verifying them fills this in.
				</p>
			{/if}
		</div>
	</div>
{/if}
