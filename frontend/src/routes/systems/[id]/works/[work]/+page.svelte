<script lang="ts">
	import { page } from '$app/state';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import EntityHeader from '$lib/components/EntityHeader.svelte';
	import BackLink from '$lib/components/BackLink.svelte';
	import SectionCard from '$lib/components/SectionCard.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import * as Alert from '$lib/components/ui/alert';
	import { api, ApiError, type FormalSystemDetail, type WorkCitations } from '$lib/api';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';

	let system = $state<FormalSystemDetail | null>(null);
	let cited = $state<WorkCitations | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let loadSeq = 0;

	// The head of the list is what a reader follows; the rest is a count. Capped
	// server-side (`WORK_LABEL_LIMIT`) — set.mm cites `[Crawley]` 520 times.
	const hidden = $derived((cited?.cited_by_total ?? 0) - (cited?.cited_by.length ?? 0));

	async function load(systemId: string, work: string) {
		const seq = ++loadSeq;
		loading = true;
		error = null;
		try {
			const [detail, found] = await Promise.all([
				api.systems.get(systemId),
				api.systems.work(systemId, work)
			]);
			if (seq !== loadSeq) return;
			system = detail;
			cited = found;
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

	$effect(() => {
		const id = page.params.id;
		const work = page.params.work;
		if (id && work) load(id, work);
	});
</script>

<PageContainer maxWidth="3xl" gap>
	<BackLink href={`/systems/${page.params.id}/works`} label="Back to works cited" />

	{#if error}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>System unavailable</Alert.Title>
			<Alert.Description>{error}</Alert.Description>
		</Alert.Root>
	{:else if loading || !system || !cited}
		<LoadingSpinner message="Loading citations…" />
	{:else}
		<EntityHeader title={cited.work} subtitle={system.name} />

		{#if cited.cited_by.length === 0}
			<SectionCard variant="muted">
				<p class="text-sm text-muted-foreground">
					Nothing in this system cites <span class="font-mono">{cited.work}</span>.
				</p>
			</SectionCard>
		{:else}
			<p class="text-sm text-muted-foreground">
				{cited.cited_by_total}
				{cited.cited_by_total === 1 ? 'statement comes' : 'statements come'} from this work.
			</p>
			<ul class="flex flex-col gap-2">
				{#each cited.cited_by as entry (entry.label)}
					<li>
						{#if entry.proof_id}
							<a
								href={`/proofs/${entry.proof_id}`}
								class="flex items-center justify-between gap-3 rounded-lg border p-3 hover:bg-muted/40"
							>
								<span class="shrink-0 font-mono text-sm">{entry.label}</span>
								{#if entry.title}
									<span class="min-w-0 truncate text-xs text-muted-foreground"
										>{entry.title}</span
									>
								{/if}
							</a>
						{:else}
							<!-- A `$a` has no page of its own: an axiom or a definition is
							     documented and cited but was never proved. -->
							<div class="flex items-center justify-between gap-3 rounded-lg border p-3">
								<span class="shrink-0 font-mono text-sm">{entry.label}</span>
								{#if entry.title}
									<span class="min-w-0 truncate text-xs text-muted-foreground"
										>{entry.title}</span
									>
								{/if}
							</div>
						{/if}
					</li>
				{/each}
				{#if hidden > 0}
					<li class="text-xs text-muted-foreground">and {hidden} more</li>
				{/if}
			</ul>
		{/if}
	{/if}
</PageContainer>
