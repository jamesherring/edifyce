<script lang="ts">
	import { page } from '$app/state';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import EntityHeader from '$lib/components/EntityHeader.svelte';
	import BackLink from '$lib/components/BackLink.svelte';
	import SectionCard from '$lib/components/SectionCard.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import DetailField from '$lib/components/DetailField.svelte';
	import { Badge } from '$lib/components/ui/badge';
	import * as Alert from '$lib/components/ui/alert';
	import { api, ApiError, type AssumptionDetail } from '$lib/api';
	import { formatDate } from '$lib/format';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';

	let assumption = $state<AssumptionDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let loadSeq = 0;

	async function load(systemId: string, label: string) {
		const seq = ++loadSeq;
		loading = true;
		error = null;
		try {
			const found = await api.assumptions.get(systemId, label);
			if (seq !== loadSeq) return;
			assumption = found;
		} catch (err) {
			if (seq !== loadSeq) return;
			assumption = null;
			error =
				err instanceof ApiError
					? err.status === 404
						? 'No such assumption — it may have been withdrawn or discharged by a proof.'
						: err.message
					: String(err);
		} finally {
			if (seq === loadSeq) loading = false;
		}
	}

	$effect(() => {
		const id = page.params.id;
		const label = page.params.label;
		if (id && label) load(id, label);
	});
</script>

<PageContainer maxWidth="3xl" gap>
	<BackLink href={`/systems/${page.params.id}/assumptions`} label="Back to assumptions" />

	{#if error}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>Assumption unavailable</Alert.Title>
			<Alert.Description>{error}</Alert.Description>
		</Alert.Root>
	{:else if loading || !assumption}
		<LoadingSpinner message="Loading assumption…" />
	{:else}
		<EntityHeader title={assumption.label} subtitle={assumption.formal_system_name}>
			{#snippet badges()}
				<!-- A snippet is its own closure, so the narrowing above does not reach
				     in; re-checking here is what makes `assumption` non-null. -->
				{#if assumption}
					<Badge variant="secondary" class="tabular-nums">
						{assumption.dependents}
						{assumption.dependents === 1 ? 'dependent' : 'dependents'}
					</Badge>
					<span class="text-xs text-muted-foreground">
						Taken on {formatDate(assumption.created_at)}
					</span>
				{/if}
			{/snippet}
		</EntityHeader>

		<SectionCard>
			<div class="flex flex-col gap-4">
				<DetailField label="Statement">
					<code class="block whitespace-pre-wrap break-words font-mono text-sm"
						>{assumption.statement}</code
					>
				</DetailField>
				<DetailField label="Why it is assumed" mono={false} value={assumption.reason} />
				{#if assumption.source}
					<DetailField label="Source" mono={false} value={assumption.source} />
				{/if}
			</div>
		</SectionCard>

		<SectionCard title="What rests on it">
			{#if assumption.dependent_labels.length === 0}
				<p class="text-sm text-muted-foreground">
					Nothing in this system's library rests on it yet. It can be withdrawn without
					leaving anything standing on nothing.
				</p>
			{:else}
				<p class="mb-3 text-sm text-muted-foreground">
					These library entries inherit the debt — transitively, so one three hops away and
					naming it nowhere is here too. Each is a complete proof of an implication until
					this is discharged.
				</p>
				<ul class="flex flex-wrap gap-1.5">
					{#each assumption.dependent_labels as label (label)}
						<li class="rounded border px-2 py-0.5 font-mono text-xs">{label}</li>
					{/each}
				</ul>
			{/if}
		</SectionCard>
	{/if}
</PageContainer>
