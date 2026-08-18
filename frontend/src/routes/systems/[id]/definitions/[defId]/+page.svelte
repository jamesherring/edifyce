<script lang="ts">
	import { page } from '$app/state';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import EntityHeader from '$lib/components/EntityHeader.svelte';
	import BackLink from '$lib/components/BackLink.svelte';
	import SectionCard from '$lib/components/SectionCard.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import { Button } from '$lib/components/ui/button';
	import { Badge } from '$lib/components/ui/badge';
	import * as Alert from '$lib/components/ui/alert';
	import { auth } from '$lib/auth.svelte';
	import { api, ApiError, type Definition, type FormalSystemDetail } from '$lib/api';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Layers from '@lucide/svelte/icons/layers';

	let system = $state<FormalSystemDetail | null>(null);
	let definition = $state<Definition | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let loadSeq = 0;

	async function load(systemId: string, defId: string) {
		const seq = ++loadSeq;
		loading = true;
		error = null;
		try {
			const detail = await api.systems.get(systemId);
			if (seq !== loadSeq) return;
			system = detail;
			definition = detail.definitions.find((d) => d.id === defId) ?? null;
			if (definition === null) error = 'This definition does not exist in this system.';
		} catch (err) {
			if (seq !== loadSeq) return;
			system = null;
			definition = null;
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

	const isOwner = $derived(!!auth.user && !!system && system.owner?.id === auth.user.id);
	const bindingText = (b: { var: string; sort: string }) => `${b.var} : ${b.sort}`;

	$effect(() => {
		const { id, defId } = page.params;
		if (id && defId) load(id, defId);
	});
</script>

<svelte:head><title>{definition?.name ?? 'Definition'} — Edifyce</title></svelte:head>

<PageContainer maxWidth="3xl" gap>
	<BackLink href={`/systems/${page.params.id}/definitions`} label="All definitions" />

	{#if error}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>Definition unavailable</Alert.Title>
			<Alert.Description>{error}</Alert.Description>
		</Alert.Root>
	{:else if loading || !definition || !system}
		<LoadingSpinner message="Loading definition…" />
	{:else if definition && system}
		<EntityHeader title={definition.name}>
			{#snippet badges()}
				<Badge variant="secondary" class="font-mono">{definition?.sort}</Badge>
			{/snippet}
			{#snippet actions()}
				<div class="flex flex-wrap gap-2">
					{#if isOwner}
						<Button href={`/systems/${system?.id}/edit`} variant="outline" size="sm">
							<Pencil class="size-4" /> Edit in system
						</Button>
					{/if}
					<Button href={`/systems/${system?.id}`} variant="outline" size="sm">
						<Layers class="size-4" /> {system?.name}
					</Button>
				</div>
			{/snippet}
		</EntityHeader>

		<SectionCard title="Definition">
			<p class="font-mono text-sm">
				<span>{definition.higher}</span>
				<span class="text-muted-foreground"> ≝ </span>
				<span>{definition.lower}</span>
			</p>
		</SectionCard>

		{#if definition.bindings.length > 0}
			<SectionCard title="Bindings">
				<ul class="flex flex-wrap gap-2">
					{#each definition.bindings as b (b.var)}
						<li class="rounded bg-muted px-2 py-0.5 font-mono text-xs">{bindingText(b)}</li>
					{/each}
				</ul>
			</SectionCard>
		{/if}

		{#if definition.fresh.length > 0}
			<SectionCard title="Bound variables (fresh)">
				<p class="mb-2 text-xs text-muted-foreground">
					Variables the expansion binds, so the definition (and its provisos) is checked
					capture-avoidingly.
				</p>
				<ul class="flex flex-wrap gap-2">
					{#each definition.fresh as b (b.var)}
						<li class="rounded bg-muted px-2 py-0.5 font-mono text-xs">{bindingText(b)}</li>
					{/each}
				</ul>
			</SectionCard>
		{/if}

		{#if definition.provisos.length > 0}
			<SectionCard title="Provisos">
				<p class="mb-2 text-xs text-muted-foreground">All must hold for the definition to apply.</p>
				<ul class="flex flex-col gap-1">
					{#each definition.provisos as proviso, i (i)}
						<li class="rounded bg-muted px-2 py-1 font-mono text-xs">{proviso}</li>
					{/each}
				</ul>
			</SectionCard>
		{/if}
	{/if}
</PageContainer>
