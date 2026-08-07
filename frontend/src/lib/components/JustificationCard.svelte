<script lang="ts">
	/**
	 * The citation on a proof line, and what it means.
	 *
	 * `[imbi12d, 2, 3]` names a step without explaining it: on a corpus of 47,589
	 * theorems a reader does not know what `imbi12d` says, let alone what it was
	 * applied to. Everything that would tell them — the rule's own schemas, which
	 * cited line filled which premise, the substitution the match derived, the
	 * provisos that had to hold — is something the checker worked out and the
	 * citation throws away.
	 *
	 * Fetched **on open**, once. The substitution is derived by the match and no
	 * stored row carries it, so the request re-checks the proof; asking for every
	 * line of a 30-step proof up front would be thirty of those for a card nobody
	 * may open.
	 */
	import * as HoverCard from '$lib/components/ui/hover-card';
	import { Badge } from '$lib/components/ui/badge';
	import Typeset from '$lib/components/Typeset.svelte';
	import { api, ApiError, type LineJustification } from '$lib/api';
	import { isTeX } from '$lib/math';
	import ExternalLink from '@lucide/svelte/icons/external-link';

	type Props = {
		/** The proof the line belongs to, and the line's citation number. Both are
		 *  needed to ask; without a proof there is nothing to ask about, and the
		 *  citation renders as plain text. */
		proofId?: string | null;
		number?: number | null;
		/** The citation as the author wrote it — what the trigger shows. */
		citation: string;
		/** The notation the proof is being read in, so the card's terms are read
		 *  the same way rather than in the spelling underneath it. */
		notation?: string | null;
	};

	let { proofId = null, number = null, citation, notation = null }: Props = $props();

	let open = $state(false);
	let told = $state<LineJustification | null>(null);
	let error = $state<string | null>(null);
	let loading = $state(false);
	// What the held record is of, so a notation change (or a different line) is
	// re-fetched rather than shown stale under the new heading.
	let fetched = $state<string | null>(null);

	const tex = $derived(told !== null && isTeX(told.notation));
	const key = $derived(`${proofId}:${number}:${notation ?? ''}`);

	async function load() {
		if (!proofId || number === null || fetched === key) return;
		loading = true;
		error = null;
		const asked = key;
		try {
			const found = await api.proofs.justification(proofId, number, notation ?? undefined);
			if (asked !== key) return;
			told = found;
			fetched = asked;
		} catch (err) {
			if (asked !== key) return;
			told = null;
			// A 404 is the ordinary answer for a line no citation justifies, so it
			// reads as an absence rather than as a fault.
			error =
				err instanceof ApiError && err.status === 404
					? 'Nothing recorded justifies this line.'
					: err instanceof ApiError
						? err.message
						: String(err);
		} finally {
			if (asked === key) loading = false;
		}
	}

	$effect(() => {
		if (open) void load();
	});
</script>

{#if proofId && number !== null}
	<HoverCard.Root bind:open openDelay={200}>
		<!-- `tabindex` because the primitive renders an anchor and this one has no
		     href: without it the trigger is unreachable by keyboard, and the card
		     opens on focus as readily as on hover. -->
		<HoverCard.Trigger
			tabindex={0}
			class="cursor-help rounded-sm underline decoration-dotted underline-offset-2 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
		>
			by {citation}
		</HoverCard.Trigger>
		<HoverCard.Content class="w-96 max-w-[calc(100vw-2rem)]" align="end">
			{#if loading && told === null}
				<p class="text-xs text-muted-foreground">Working out why this line follows…</p>
			{:else if error}
				<p class="text-xs text-muted-foreground">{error}</p>
			{:else if told}
				<div class="flex flex-col gap-3 text-left">
					<div class="flex flex-col gap-1">
						<div class="flex items-baseline justify-between gap-2">
							<code class="font-mono text-sm font-medium">{told.label}</code>
							{#if told.kind === 'definition'}
								<Badge variant="outline">definition</Badge>
							{:else if told.name && told.name !== told.label}
								<span class="shrink-0 text-xs text-muted-foreground">{told.name}</span>
							{/if}
						</div>
						{#if told.title}
							<p class="text-xs leading-relaxed text-muted-foreground">{told.title}</p>
						{/if}
					</div>

					<!-- The rule in general, against which this step is the instance. -->
					<div class="flex flex-col gap-1 border-t pt-2">
						{#each told.premises.filter((p) => !p.extra) as premise (premise.position)}
							<div class="flex items-baseline gap-2 text-xs">
								<span class="w-14 shrink-0 text-muted-foreground">premise</span>
								<span class="min-w-0 flex-1 font-mono break-words">{premise.schema_form}</span>
								{#if premise.number !== null}
									<span class="shrink-0 text-muted-foreground">line {premise.number}</span>
								{/if}
							</div>
						{/each}
						{#if told.discharges}
							<div class="flex items-baseline gap-2 text-xs">
								<span class="w-14 shrink-0 text-muted-foreground">subproof</span>
								<span class="min-w-0 flex-1 font-mono break-words">{told.discharges}</span>
							</div>
						{/if}
						<div class="flex items-baseline gap-2 text-xs">
							<span class="w-14 shrink-0 text-muted-foreground">
								{told.kind === 'definition' ? 'defines' : 'concludes'}
							</span>
							<span class="min-w-0 flex-1 font-mono break-words">{told.conclusion}</span>
						</div>
						{#each told.premises.filter((p) => p.extra) as surplus (surplus.position)}
							<!-- A line the rule tolerated but did not ask for. Dropping it would
							     leave the citation naming more lines than the card accounts for. -->
							<div class="flex items-baseline gap-2 text-xs text-muted-foreground">
								<span class="w-14 shrink-0">also cited</span>
								<span class="min-w-0 flex-1 break-words">line {surplus.number}</span>
							</div>
						{/each}
					</div>

					{#if told.assignments.length > 0}
						<!-- The half that makes the step checkable: a rule is a schema, and
						     this is what its metavariables stood for here. -->
						<div class="flex flex-col gap-1 border-t pt-2">
							<p class="text-xs font-medium">Here</p>
							{#each told.assignments as assignment (assignment.variable)}
								<div class="flex items-baseline gap-2 text-xs">
									<span class="w-14 shrink-0 font-mono">{assignment.variable}</span>
									<span class="min-w-0 flex-1 break-words">
										{#if tex}
											<Typeset tex={assignment.stands_for} />
										{:else}
											<span class="font-mono">{assignment.stands_for}</span>
										{/if}
									</span>
								</div>
							{/each}
						</div>
					{/if}

					{#if told.provisos.length > 0}
						<div class="flex flex-col gap-1 border-t pt-2">
							<p class="text-xs font-medium">Provided</p>
							{#each told.provisos as proviso, i (i)}
								<p class="font-mono text-xs break-words text-muted-foreground">
									{proviso.source}
								</p>
							{/each}
						</div>
					{/if}

					{#if told.proof_id}
						<a
							class="flex items-center gap-1 border-t pt-2 text-xs underline"
							href={`/proofs/${told.proof_id}`}
							target="_blank"
							rel="noopener"
						>
							<ExternalLink class="size-3" /> Open the proof of {told.label}
						</a>
					{/if}
				</div>
			{/if}
		</HoverCard.Content>
	</HoverCard.Root>
{:else}
	by {citation}
{/if}
