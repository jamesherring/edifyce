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
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Alert from '$lib/components/ui/alert';
	import { api, ApiError, type ProofDetail, type VerifyResponse } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import Play from '@lucide/svelte/icons/play';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Layers from '@lucide/svelte/icons/layers';

	let proof = $state<ProofDetail | null>(null);
	let systemName = $state<string | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let verifying = $state(false);
	let result = $state<VerifyResponse | null>(null);
	let requestError = $state<string | null>(null);

	// Bumped on every load so late responses from a previous id are dropped.
	let loadSeq = 0;
	let verifySeq = 0;

	async function load(id: string) {
		const seq = ++loadSeq;
		verifySeq++; // invalidate any in-flight verify from a previous proof
		verifying = false;
		loading = true;
		error = null;
		result = null;
		requestError = null;
		systemName = null;
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
		// Best-effort system name for the header link (readable proofs reference a
		// readable system, so this normally resolves).
		void loadSystemName(detail.formal_system_id, seq);
	}

	async function loadSystemName(systemId: string, seq: number) {
		try {
			const system = await api.systems.get(systemId);
			if (seq === loadSeq) systemName = system.name;
		} catch {
			// Leave the link labelled generically if the system can't be read.
		}
	}

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
		<EntityHeader title={proof.name} subtitle={proof.description ?? undefined}>
			{#snippet badges()}
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

		<div class="grid gap-6 lg:grid-cols-2">
			<Card.Root>
				<Card.Header>
					<div class="flex items-center justify-between gap-2">
						<Card.Title>Proof</Card.Title>
						<Button onclick={verify} disabled={verifying} size="sm">
							{#if verifying}
								<LoaderCircle class="size-4 animate-spin" /> Verifying…
							{:else}
								<Play class="size-4" /> Verify
							{/if}
						</Button>
					</div>
					<Card.Description>The proof source, checked line by line.</Card.Description>
				</Card.Header>
				<Card.Content>
					{#if proof.source.trim()}
						<pre class="overflow-x-auto rounded-md border bg-muted/30 p-4 font-mono text-xs leading-relaxed">{proof.source}</pre>
					{:else}
						<p class="py-6 text-center text-sm text-muted-foreground">
							This proof is empty.{#if isOwner}
								<a class="underline" href={`/proofs/${proof.id}/edit`}>Add some lines</a>.{/if}
						</p>
					{/if}
				</Card.Content>
			</Card.Root>

			<ProofResults {result} {requestError} idleMessage="Verify the proof to see line-by-line results here." />
		</div>

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
