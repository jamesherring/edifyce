<script lang="ts">
	import { page } from '$app/state';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import EntityHeader from '$lib/components/EntityHeader.svelte';
	import BackLink from '$lib/components/BackLink.svelte';
	import SectionCard from '$lib/components/SectionCard.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import AssumptionForm from '$lib/components/AssumptionForm.svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { Button } from '$lib/components/ui/button';
	import * as Alert from '$lib/components/ui/alert';
	import { auth } from '$lib/auth.svelte';
	import { api, ApiError, type Assumption, type FormalSystemDetail } from '$lib/api';
	import { systemSymbols } from '$lib/symbols';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import Plus from '@lucide/svelte/icons/plus';

	let system = $state<FormalSystemDetail | null>(null);
	let assumptions = $state<Assumption[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let adding = $state(false);
	// A withdrawal that was refused, kept beside the list rather than in the form:
	// it is a fact about one row, and the 409 says which.
	let refused = $state<string | null>(null);
	// The label whose DELETE is in flight, or null.
	let withdrawing = $state<string | null>(null);
	let loadSeq = 0;

	const isOwner = $derived(!!auth.user && !!system && system.owner?.id === auth.user.id);
	const symbols = $derived(systemSymbols(system));

	async function load(systemId: string) {
		const seq = ++loadSeq;
		loading = true;
		error = null;
		refused = null;
		try {
			const [detail, taken] = await Promise.all([
				api.systems.get(systemId),
				api.assumptions.list(systemId)
			]);
			if (seq !== loadSeq) return;
			system = detail;
			assumptions = taken;
		} catch (err) {
			if (seq !== loadSeq) return;
			system = null;
			error =
				err instanceof ApiError
					? err.status === 404
						? 'This system does not exist, or is a private draft.'
						: err.message
					: String(err);
		} finally {
			if (seq === loadSeq) loading = false;
		}
	}

	async function withdraw(label: string) {
		// Guarded, not just visually disabled: a second DELETE 404s on a row the
		// first one withdrew fine, and would report that as a refusal.
		if (!system || withdrawing) return;
		withdrawing = label;
		refused = null;
		try {
			await api.assumptions.withdraw(system.id, label);
			assumptions = assumptions.filter((one) => one.label !== label);
		} catch (err) {
			// A 409 is the interesting one: withdrawing a debt something rests on
			// would leave those entries citable and reporting no assumptions, so the
			// API refuses and the reason is worth showing verbatim.
			refused = err instanceof ApiError ? err.message : String(err);
		} finally {
			withdrawing = null;
		}
	}

	function added(one: Assumption) {
		assumptions = [...assumptions, one];
		adding = false;
	}

	$effect(() => {
		const id = page.params.id;
		if (id) load(id);
	});
</script>

<svelte:head><title>{system ? `Assumptions · ${system.name}` : 'Assumptions'} — Edifyce</title></svelte:head>

<PageContainer maxWidth="3xl" gap>
	<BackLink href={`/systems/${page.params.id}`} label="Back to system" />

	{#if error}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>System unavailable</Alert.Title>
			<Alert.Description>{error}</Alert.Description>
		</Alert.Root>
	{:else if loading || !system}
		<LoadingSpinner message="Loading assumptions…" />
	{:else}
		<EntityHeader title="Assumptions" subtitle={system.name}>
			{#snippet actions()}
				{#if isOwner && !adding}
					<Button variant="outline" size="sm" onclick={() => (adding = true)}>
						<Plus class="size-4" /> Take one on
					</Button>
				{/if}
			{/snippet}
		</EntityHeader>

		<p class="text-sm text-muted-foreground">
			Statements this system offers without proving them. A proof citing one is a complete
			proof of an implication — which is a legitimate thing to have, so long as it is not
			silent.
		</p>

		{#if adding && system}
			<AssumptionForm
				systemId={system.id}
				{symbols}
				oncreated={added}
				oncancel={() => (adding = false)}
			/>
		{/if}

		{#if refused}
			<Alert.Root variant="destructive">
				<TriangleAlert class="size-4" />
				<Alert.Title>Cannot withdraw</Alert.Title>
				<Alert.Description>{refused}</Alert.Description>
			</Alert.Root>
		{/if}

		{#if assumptions.length === 0}
			<SectionCard variant="muted">
				<p class="text-sm text-muted-foreground">
					This system assumes nothing. Everything it offers has a proof or is a declared
					primitive of the theory.
				</p>
			</SectionCard>
		{:else}
			<ul class="flex flex-col gap-2">
				{#each assumptions as one (one.id)}
					<li class="flex flex-col gap-1.5 rounded-lg border p-3">
						<div class="flex items-start justify-between gap-3">
							<a
								href={`/systems/${system.id}/assumptions/${encodeURIComponent(one.label)}`}
								class="font-mono text-sm underline decoration-dotted underline-offset-2 hover:decoration-solid"
								>{one.label}</a
							>
							<div class="flex shrink-0 items-center gap-2">
								<!-- The blast radius, and the ranking that says which gap is worth
								     closing first. Counts entries transitively, so one three hops
								     away and naming this nowhere still counts. -->
								<Badge variant="secondary" class="tabular-nums">
									{one.dependents}
									{one.dependents === 1 ? 'dependent' : 'dependents'}
								</Badge>
								{#if isOwner}
									<Button
										variant="ghost"
										size="sm"
										disabled={withdrawing !== null}
										onclick={() => withdraw(one.label)}
									>
										{withdrawing === one.label ? 'Withdrawing…' : 'Withdraw'}
									</Button>
								{/if}
							</div>
						</div>
						<code class="whitespace-pre-wrap break-words font-mono text-xs">{one.statement}</code>
						<p class="text-xs text-muted-foreground">
							{one.reason}{#if one.source}
								— <span class="italic">{one.source}</span>{/if}
						</p>
					</li>
				{/each}
			</ul>
		{/if}
	{/if}
</PageContainer>
