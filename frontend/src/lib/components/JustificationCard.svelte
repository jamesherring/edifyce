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
	 *
	 * Two sources, because only half of it costs that. What the citation *says* —
	 * the rule, its schemas, the corpus's note about it, where its proof is — is
	 * rows, and any reader of the system may have it (`systems.libraryEntry`).
	 * Only the substitution needs the re-check, and a re-check is signed-in only
	 * (see `explain_line`), so a signed-out reader gets the card without its
	 * "Here" section rather than no card at all.
	 */
	import * as HoverCard from '$lib/components/ui/hover-card';
	import { Badge } from '$lib/components/ui/badge';
	import Typeset from '$lib/components/Typeset.svelte';
	import { api, ApiError, type LibraryEntry, type LineJustification } from '$lib/api';
	import { isTeX } from '$lib/math';
	import ExternalLink from '@lucide/svelte/icons/external-link';

	type Props = {
		/** The proof the line belongs to. Always worth passing: it resolves a label
		 *  local to that proof — a hypothesis of the theorem it establishes — which
		 *  no system-wide lookup can see. */
		proofId?: string | null;
		/** The line's citation number, and whether this reader may pay for the
		 *  substitution. Both are needed for it; without them the card still opens,
		 *  on what the label alone says. */
		number?: number | null;
		explain?: boolean;
		/** The system the citation resolves in, and the label the checker resolved
		 *  it to — what the rows-only half is asked by. Without them the citation
		 *  renders as plain text, since there is nothing to look up. */
		systemId?: string | null;
		label?: string | null;
		/** The citation as the author wrote it — what the trigger shows. */
		citation: string;
		/** The notation the proof is being read in, so the card's terms are read
		 *  the same way rather than in the spelling underneath it. */
		notation?: string | null;
	};

	let {
		proofId = null,
		number = null,
		explain = false,
		systemId = null,
		label = null,
		citation,
		notation = null
	}: Props = $props();

	let open = $state(false);
	let told = $state<LineJustification | null>(null);
	let says = $state<LibraryEntry | null>(null);
	let error = $state<string | null>(null);
	let loading = $state(false);
	// What the held record is of, so a notation change (or a different line) is
	// re-fetched rather than shown stale under the new heading.
	let fetched = $state<string | null>(null);

	// Whichever source answered, its own echo of the notation decides — never the
	// selection, which may be a fetch ahead of what is on screen.
	const tex = $derived(isTeX(told?.notation ?? says?.notation ?? null));
	const key = $derived(`${proofId}:${number}:${systemId}:${label}:${notation ?? ''}`);
	// The substitution is the only part a re-check buys, so it is asked for only
	// where a reader may pay for one.
	const explains = $derived(explain && proofId !== null && number !== null);
	// One shape either way: the rich record where there is one, the rows where
	// there is not.
	const shown = $derived(
		told ??
			(says &&
				({
					label: says.label,
					name: says.name,
					kind: says.kind === 'rule' ? 'rule' : says.kind,
					conclusion: says.conclusion,
					premises: says.premises.map((schema_form, position) => ({
						position,
						schema_form,
						number: null,
						statement: null,
						extra: false
					})),
					assignments: [],
					provisos: [],
					discharges: says.discharges,
					title: says.title,
					proof_id: says.proof_id,
					notation: says.notation
				} satisfies Omit<LineJustification, 'line' | 'citation'>))
	);

	async function load() {
		if (fetched === key) return;
		if (!explains && !(systemId && label)) return;
		// Dropped before the fetch, not after it: the held record is of another
		// reading, and leaving it up would show the previous notation's
		// substitution under the new one's heading for the whole round trip —
		// exactly the staleness the key exists to catch.
		told = null;
		says = null;
		fetched = null;
		loading = true;
		error = null;
		const asked = key;
		try {
			if (explains) {
				const found = await api.proofs.justification(proofId!, number!, notation ?? undefined);
				if (asked !== key) return;
				told = found;
			} else {
				const found = await api.systems.libraryEntry(systemId!, label!, {
					notation: notation ?? undefined,
					proof: proofId ?? undefined
				});
				if (asked !== key) return;
				says = found;
			}
			fetched = asked;
		} catch (err) {
			if (asked !== key) return;
			told = null;
			says = null;
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

	// On `key` as well as on `open`: the notation can change while the card is up,
	// and re-reading is what a switch means.
	$effect(() => {
		key;
		if (open) void load();
	});
</script>

{#if (proofId && number !== null) || (systemId && label)}
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
			{#if loading && shown === null}
				<p class="text-xs text-muted-foreground">Working out why this line follows…</p>
			{:else if error}
				<p class="text-xs text-muted-foreground">{error}</p>
			{:else if shown}
				<div class="flex flex-col gap-3 text-left">
					<div class="flex flex-col gap-1">
						<div class="flex items-baseline justify-between gap-2">
							<!-- An unlabelled definition reports no label: `Def` is how a
							     citation reaches one, not a name it has. -->
							<code class="font-mono text-sm font-medium">{shown.label || 'definition'}</code>
							{#if shown.kind === 'definition'}
								<Badge variant="outline">definition</Badge>
							{:else if shown.name && shown.name !== shown.label}
								<span class="shrink-0 text-xs text-muted-foreground">{shown.name}</span>
							{/if}
						</div>
						{#if shown.title}
							<p class="text-xs leading-relaxed text-muted-foreground">{shown.title}</p>
						{/if}
					</div>

					<!-- The rule in general, against which this step is the instance. -->
					<div class="flex flex-col gap-1 border-t pt-2">
						{#each shown.premises.filter((p) => !p.extra) as premise (premise.position)}
							<div class="flex items-baseline gap-2 text-xs">
								<span class="w-14 shrink-0 text-muted-foreground">premise</span>
								<span class="min-w-0 flex-1 break-words">
									{#if tex}
										<Typeset tex={premise.schema_form} />
									{:else}
										<span class="font-mono">{premise.schema_form}</span>
									{/if}
								</span>
								{#if premise.number !== null}
									<span class="shrink-0 text-muted-foreground">line {premise.number}</span>
								{/if}
							</div>
						{/each}
						{#if shown.discharges}
							<div class="flex items-baseline gap-2 text-xs">
								<span class="w-14 shrink-0 text-muted-foreground">subproof</span>
								<span class="min-w-0 flex-1 break-words">
									{#if tex}
										<Typeset tex={shown.discharges} />
									{:else}
										<span class="font-mono">{shown.discharges}</span>
									{/if}
								</span>
							</div>
						{/if}
						<div class="flex items-baseline gap-2 text-xs">
							<span class="w-14 shrink-0 text-muted-foreground">
								{shown.kind === 'definition' ? 'defines' : 'concludes'}
							</span>
							<span class="min-w-0 flex-1 break-words">
								{#if tex}
									<Typeset tex={shown.conclusion} />
								{:else}
									<span class="font-mono">{shown.conclusion}</span>
								{/if}
							</span>
						</div>
						{#each shown.premises.filter((p) => p.extra) as surplus (surplus.position)}
							<!-- A line the rule tolerated but did not ask for. Dropping it would
							     leave the citation naming more lines than the card accounts for. -->
							<div class="flex items-baseline gap-2 text-xs text-muted-foreground">
								<span class="w-14 shrink-0">also cited</span>
								<span class="min-w-0 flex-1 break-words">line {surplus.number}</span>
							</div>
						{/each}
					</div>

					{#if shown.assignments.length > 0}
						<!-- The half that makes the step checkable: a rule is a schema, and
						     this is what its metavariables stood for here. -->
						<div class="flex flex-col gap-1 border-t pt-2">
							<p class="text-xs font-medium">Here</p>
							{#each shown.assignments as assignment (assignment.variable)}
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

					{#if shown.provisos.length > 0}
						<div class="flex flex-col gap-1 border-t pt-2">
							<p class="text-xs font-medium">Provided</p>
							{#each shown.provisos as proviso, i (i)}
								<p class="font-mono text-xs break-words text-muted-foreground">
									{proviso.source}
								</p>
							{/each}
						</div>
					{/if}

					{#if shown.proof_id}
						<a
							class="flex items-center gap-1 border-t pt-2 text-xs underline"
							href={`/proofs/${shown.proof_id}`}
							target="_blank"
							rel="noopener"
						>
							<ExternalLink class="size-3" /> Open the proof of {shown.label}
						</a>
					{/if}
				</div>
			{/if}
		</HoverCard.Content>
	</HoverCard.Root>
{:else}
	by {citation}
{/if}
