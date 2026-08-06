<script lang="ts">
	import { page } from '$app/state';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import EntityHeader from '$lib/components/EntityHeader.svelte';
	import EntityFooter from '$lib/components/EntityFooter.svelte';
	import BackLink from '$lib/components/BackLink.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import CheckBadge from '$lib/components/CheckBadge.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import ProofResults from '$lib/components/ProofResults.svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Alert from '$lib/components/ui/alert';
	import {
		api,
		ApiError,
		type ProofDetail,
		type ProofStructure,
		type VerifyResponse
	} from '$lib/api';
	import { readLines } from '$lib/reading';
	import { isTeX } from '$lib/math';
	import { auth } from '$lib/auth.svelte';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import Play from '@lucide/svelte/icons/play';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Layers from '@lucide/svelte/icons/layers';

	let proof = $state<ProofDetail | null>(null);
	let systemName = $state<string | null>(null);
	// Where the system came from, when it was not authored here. Recorded once per
	// import rather than on each of its proofs, so it is read off the system.
	let provenance = $state<string | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let verifying = $state(false);
	let result = $state<VerifyResponse | null>(null);
	let requestError = $state<string | null>(null);

	// How the proof is being read. `null` is the source it was written in; the
	// rest are the parent system's stored notations. Either way the *rows* come
	// from the stored structure, which is what carries a re-spelled term beside
	// the checker's verdict on the line it belongs to.
	let notations = $state<string[]>([]);
	let notation = $state<string | null>(null);
	let structure = $state<ProofStructure | null>(null);
	let notationError = $state<string | null>(null);
	let reading = $state(false);

	// Bumped on every load so late responses from a previous id are dropped.
	let loadSeq = 0;
	let verifySeq = 0;
	let notationSeq = 0;

	async function load(id: string) {
		const seq = ++loadSeq;
		// Invalidate anything in flight for the previous proof: a late response
		// would otherwise render its lines, or its error, inside this page.
		verifySeq++;
		notationSeq++;
		verifying = false;
		reading = false;
		loading = true;
		error = null;
		result = null;
		requestError = null;
		systemName = null;
		provenance = null;
		notations = [];
		notation = null;
		structure = null;
		notationError = null;
		let detail: ProofDetail;
		try {
			detail = await api.proofs.get(id);
		} catch (err) {
			if (seq !== loadSeq) return;
			error =
				err instanceof ApiError
					? err.status === 404
						? 'This proof does not exist, or is a private draft.'
						: err.message
					: String(err);
			proof = null;
			loading = false;
			return;
		}
		if (seq !== loadSeq) return;
		proof = detail;
		loading = false;
		// Show the last cached verdict immediately, so a revisit isn't blank.
		if (detail.result) result = { success: detail.valid ?? false, errors: [], proof: detail.result };
		// The rows this page shows, in the source spelling to begin with.
		void readIn(null);
		// Best-effort system name for the header link (readable proofs reference a
		// readable system, so this normally resolves).
		void loadSystemName(detail.formal_system_id, seq);
	}

	async function loadSystemName(systemId: string, seq: number) {
		try {
			const system = await api.systems.get(systemId);
			if (seq !== loadSeq) return;
			systemName = system.name;
			notations = system.notations;
			provenance = system.provenance;
		} catch {
			// Leave the link labelled generically if the system can't be read, and
			// offer no notations — the source spelling is always readable.
		}
	}

	async function readIn(name: string | null) {
		const seq = ++notationSeq;
		notation = name;
		notationError = null;
		if (!proof) {
			reading = false;
			return;
		}
		// Keep the previous reading up while the next is fetched: switching
		// notation re-spells the same checked lines, and blanking the proof to
		// re-render it a moment later reads as the page losing its content.
		reading = true;
		try {
			const read = await api.proofs.structure(proof.id, name ?? undefined);
			if (seq === notationSeq) structure = read;
		} catch (err) {
			if (seq !== notationSeq) return;
			structure = null;
			notationError = err instanceof ApiError ? err.message : String(err);
		} finally {
			if (seq === notationSeq) reading = false;
		}
	}

	// Null until a check has stored terms to project: a proof checked before this
	// store existed, or never checked at all, has nothing to read and falls back
	// to the source it was written in.
	const rows = $derived(readLines(structure));

	// `name` is what a citation spells and what the slug is built from; `title` is
	// the sentence a human reads. Lead with the sentence where there is one — on
	// an imported corpus `name` is an opaque label — and keep the label beside it,
	// since it is the identity the rest of the library refers to.
	const heading = $derived(proof?.title ?? proof?.name ?? '');
	const label = $derived(proof?.title ? proof.name : null);
	// A proof may carry both a title and a description, and the header shows one
	// line; the description gets a place of its own so setting a title never makes
	// an author's own prose vanish from the page.
	const ownDescription = $derived(
		proof?.description && proof.description !== proof.title ? proof.description : null
	);
	const documentation = $derived(
		proof?.documentation &&
			(proof.documentation.text || proof.documentation.attributions.length > 0)
			? proof.documentation
			: null
	);

	async function verify() {
		if (!proof) return;
		const seq = ++verifySeq;
		verifying = true;
		result = null;
		requestError = null;
		try {
			const res = await api.proofs.verify(proof.id);
			if (seq !== verifySeq) return;
			result = res;
			// A check rewrites the structure the rows are read from, so what is on
			// screen is the previous check's.
			void readIn(notation);
		} catch (err) {
			if (seq !== verifySeq) return;
			requestError = err instanceof ApiError ? err.message : String(err);
		} finally {
			if (seq === verifySeq) verifying = false;
		}
	}

	const isOwner = $derived(!!auth.user && !!proof && proof.owner?.id === auth.user.id);

	$effect(() => {
		const id = page.params.id;
		if (id) load(id);
	});
</script>

<PageContainer maxWidth="5xl" gap>
	<BackLink href="/proofs" label="All proofs" />

	{#if error}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>Proof unavailable</Alert.Title>
			<Alert.Description>{error}</Alert.Description>
		</Alert.Root>
	{:else if loading || !proof}
		<LoadingSpinner message="Loading proof…" />
	{:else}
		<EntityHeader title={heading}>
			{#snippet badges()}
				{#if label}
					<Badge variant="outline" class="font-mono">{label}</Badge>
				{/if}
				<StatusBadge status={proof?.published_at ? 'published' : 'draft'} />
				<CheckBadge valid={proof?.valid ?? null} />
				{#if proof?.owner?.display_name}
					<span class="text-xs text-muted-foreground">by {proof.owner.display_name}</span>
				{/if}
			{/snippet}
			{#snippet actions()}
				<div class="flex flex-wrap gap-2">
					{#if isOwner}
						<Button href={`/proofs/${proof?.id}/edit`} variant="outline" size="sm">
							<Pencil class="size-4" /> Edit
						</Button>
					{/if}
					<Button href={`/systems/${proof?.formal_system_id}`} variant="outline" size="sm">
						<Layers class="size-4" /> {systemName ? `System: ${systemName}` : 'View system'}
					</Button>
				</div>
			{/snippet}
		</EntityHeader>

		<!-- Ahead of the proof: what a theorem says and who proved it is what a
		     reader wants first, and the lines are long. -->
		{#if ownDescription || documentation || provenance}
			<Card.Root>
				<Card.Header>
					<Card.Title>About</Card.Title>
					{#if documentation}
						<Card.Description>
							What {systemName ?? 'this system'} records about
							<code class="rounded bg-muted px-1 py-0.5 text-xs">{documentation.label}</code>.
						</Card.Description>
					{/if}
				</Card.Header>
				<Card.Content class="flex flex-col gap-4">
					{#if ownDescription}
						<p class="whitespace-pre-line text-sm leading-relaxed">{ownDescription}</p>
					{/if}
					{#if documentation?.text}
						<!-- Paragraphs survive storage as blank lines, which is how a
						     comment marks them; `whitespace-pre-line` is what shows them. -->
						<p class="whitespace-pre-line text-sm leading-relaxed">{documentation.text}</p>
					{/if}
					{#if documentation && documentation.attributions.length > 0}
						<ul class="flex flex-col gap-1 border-t pt-3">
							{#each documentation.attributions as credit, i (i)}
								<li class="text-xs text-muted-foreground">
									<span class="font-medium">{credit.kind}</span> by {credit.who}, {credit.dated}
								</li>
							{/each}
						</ul>
					{/if}
					{#if provenance}
						<!-- The system's, shown on every proof of it: an imported proof has
						     no author to credit and the library it came from is the credit. -->
						<p class="border-t pt-3 text-xs text-muted-foreground">{provenance}</p>
					{/if}
				</Card.Content>
			</Card.Root>
		{/if}

		<ProofResults
			{result}
			{requestError}
			lines={rows}
			tex={isTeX(notation)}
			title="Proof"
			description={notation === null
				? 'The proof source, checked line by line.'
				: `The same checked proof, read in ${notation}.`}
			idleMessage="Verify the proof to see it line by line."
		>
			{#snippet actions()}
				<Button onclick={verify} disabled={verifying} size="sm">
					{#if verifying}
						<LoaderCircle class="size-4 animate-spin" /> Verifying…
					{:else}
						<Play class="size-4" /> Verify
					{/if}
				</Button>
			{/snippet}
			{#snippet controls()}
				{#if notations.length > 0}
					<div class="flex flex-wrap items-center gap-1 pt-1" role="group" aria-label="Notation">
						<Button
							variant={notation === null ? 'secondary' : 'ghost'}
							size="sm"
							onclick={() => readIn(null)}>Source</Button
						>
						{#each notations as name (name)}
							<Button
								variant={notation === name ? 'secondary' : 'ghost'}
								size="sm"
								onclick={() => readIn(name)}>{name}</Button
							>
						{/each}
					</div>
				{/if}
				{#if notationError}
					<Alert.Root variant="destructive" class="mt-2">
						<TriangleAlert class="size-4" />
						<Alert.Description>{notationError}</Alert.Description>
					</Alert.Root>
				{:else if reading && rows === null}
					<p class="pt-2 text-xs text-muted-foreground">Reading…</p>
				{/if}
			{/snippet}
		</ProofResults>

		{#if rows === null && proof.source.trim()}
			<!-- No stored structure: a proof never checked, or checked before the
			     store existed. Its source is still the proof, so show that rather
			     than nothing. -->
			<Card.Root>
				<Card.Header>
					<Card.Title>Source</Card.Title>
					<Card.Description>As written; verify it to see it line by line.</Card.Description>
				</Card.Header>
				<Card.Content>
					<pre class="overflow-x-auto rounded-md border bg-muted/30 p-4 font-mono text-xs leading-relaxed">{proof.source}</pre>
				</Card.Content>
			</Card.Root>
		{/if}

		{#if proof.references.length > 0 || proof.referenced_by.length > 0}
			<div class="grid gap-6 lg:grid-cols-2">
				{#if proof.references.length > 0}
					<Card.Root>
						<Card.Header>
							<Card.Title>References</Card.Title>
							<Card.Description>Lemmas this proof cites from other proofs.</Card.Description>
						</Card.Header>
						<Card.Content>
							<ul class="flex flex-col gap-2">
								{#each proof.references as ref (ref.referenced_proof_id)}
									<li class="flex items-center justify-between gap-2 text-sm">
										<a class="truncate underline" href={`/proofs/${ref.referenced_proof_id}`}>{ref.name}</a>
										<div class="flex shrink-0 items-center gap-2">
											{#if !ref.published}
												<span class="text-xs text-muted-foreground">draft</span>
											{/if}
											<code class="rounded bg-muted px-1 py-0.5 text-xs">[{ref.alias}.line]</code>
										</div>
									</li>
								{/each}
							</ul>
						</Card.Content>
					</Card.Root>
				{/if}

				{#if proof.referenced_by.length > 0}
					<Card.Root>
						<Card.Header>
							<Card.Title>Used by</Card.Title>
							<Card.Description>Proofs that cite this one as a lemma.</Card.Description>
						</Card.Header>
						<Card.Content>
							<ul class="flex flex-col gap-2">
								{#each proof.referenced_by as ref (ref.proof_id)}
									<li class="flex items-center justify-between gap-2 text-sm">
										<a class="truncate underline" href={`/proofs/${ref.proof_id}`}>{ref.name}</a>
										<div class="flex shrink-0 items-center gap-2">
											{#if !ref.published}
												<span class="text-xs text-muted-foreground">draft</span>
											{/if}
											<code class="rounded bg-muted px-1 py-0.5 text-xs">[{ref.alias}.line]</code>
										</div>
									</li>
								{/each}
							</ul>
						</Card.Content>
					</Card.Root>
				{/if}
			</div>
		{/if}

		<EntityFooter id={proof.id} createdAt={proof.created_at} />
	{/if}
</PageContainer>
