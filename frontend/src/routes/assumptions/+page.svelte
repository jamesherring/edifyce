<script lang="ts">
	import { untrack } from 'svelte';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { Button } from '$lib/components/ui/button';
	import * as Alert from '$lib/components/ui/alert';
	import { api, ApiError, type Assumption } from '$lib/api';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';

	const PAGE_SIZE = 20;

	let items = $state<Assumption[]>([]);
	let offset = 0;
	let total = $state(0);
	// Whether the server has run out of rows to send. The *end condition*, in place
	// of `items.length < total`: the set can change between requests, so a merge
	// that drops a duplicate leaves the two permanently out of step and a
	// count-based test would offer a button that fetches nothing forever.
	let exhausted = $state(false);
	let loading = $state(true);
	let error = $state<string | null>(null);

	// Appended rather than paged over: the ranking only means something across the
	// whole set (the API orders in the database for exactly that reason), so
	// reading down the list is the way through it, and a page-2 button would
	// invite reading a slice as a ranking of its own.
	async function more() {
		loading = true;
		error = null;
		try {
			const page = await api.assumptions.public({ limit: PAGE_SIZE, offset });
			// The cursor counts what the server sent, not what survived the merge —
			// advancing by the kept rows would stall on a page that was entirely
			// duplicate.
			offset += page.items.length;
			// A short page is the end of what paging can reach, whatever `total` says.
			// Measured against the limit the *server* echoes, which is what actually
			// bounded the result — it clamps anything above its own maximum.
			exhausted = page.items.length < page.limit;
			// Deduped: this pages by offset over a set that can change between
			// requests, so a row shifting across the boundary arrives twice — and
			// twice under one key is a thrown error, not a repeated row.
			const seen = new Set(items.map((one) => one.id));
			items = [...items, ...page.items.filter((one) => !seen.has(one.id))];
			total = page.total;
		} catch (err) {
			error = err instanceof ApiError ? err.message : String(err);
		} finally {
			loading = false;
		}
	}

	// Untracked: `more` reads `items` to dedupe against, and writes it — tracked,
	// the first page would fetch the second, and so on.
	$effect(() => {
		untrack(() => {
			more();
		});
	});
</script>

<svelte:head><title>Assumptions — Edifyce</title></svelte:head>

<PageContainer maxWidth="3xl" gap>
	<PageHeader
		title="Assumptions"
		description="Statements published systems take on without proving them, most depended-on first."
	/>

	<p class="text-sm text-muted-foreground">
		Every row is something believed true that this database cannot yet justify, and the
		count says how much has been built on it. That ranking is the roadmap: the assumption a
		hundred entries rest on is where proving effort buys the most.
	</p>

	<!-- Banner, not a replacement: a failed "Show more" must leave the rows that
	     did load — and the button that retries — on the page. -->
	{#if error}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>Could not load assumptions</Alert.Title>
			<Alert.Description>{error}</Alert.Description>
		</Alert.Root>
	{/if}

	{#if loading && items.length === 0}
		<LoadingSpinner message="Loading assumptions…" />
	{:else if items.length === 0}
		<!-- Only after a clean read: a first page that failed has nothing to show,
		     but it has not established that nothing is assumed. -->
		{#if !error}
			<EmptyState
				title="Nothing is assumed"
				description="Every published system's library rests on proofs and its own declared primitives."
			/>
		{/if}
	{:else}
		<ul class="flex flex-col gap-2">
			{#each items as one (one.id)}
				<li>
					<a
						href={`/systems/${one.formal_system_id}/assumptions/${encodeURIComponent(one.label)}`}
						class="flex flex-col gap-1.5 rounded-lg border p-3 hover:bg-muted/40"
					>
						<div class="flex items-start justify-between gap-3">
							<span class="font-mono text-sm">{one.label}</span>
							<Badge variant="secondary" class="shrink-0 tabular-nums">
								{one.dependents}
								{one.dependents === 1 ? 'dependent' : 'dependents'}
							</Badge>
						</div>
						<code class="whitespace-pre-wrap break-words font-mono text-xs text-muted-foreground"
							>{one.statement}</code
						>
						<p class="text-xs text-muted-foreground">
							{one.formal_system_name} — {one.reason}
						</p>
					</a>
				</li>
			{/each}
		</ul>
	{/if}

	<!-- Outside the list: a first page that failed shows no rows and no total, and
	     still needs the retry. -->
	{#if (items.length > 0 && !exhausted) || error}
		<div class="flex items-center justify-center gap-3">
			{#if total > 0}
				<span class="text-xs text-muted-foreground">
					Showing {items.length} of {total}
				</span>
			{/if}
			<Button variant="outline" size="sm" onclick={more} disabled={loading}>
				{loading ? 'Loading…' : error ? 'Try again' : 'Show more'}
			</Button>
		</div>
	{/if}
</PageContainer>
