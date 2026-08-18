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
	import { api, ApiError, type FormalSystemDetail } from '$lib/api';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Layers from '@lucide/svelte/icons/layers';

	let system = $state<FormalSystemDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let loadSeq = 0;

	async function load(systemId: string) {
		const seq = ++loadSeq;
		loading = true;
		error = null;
		try {
			const detail = await api.systems.get(systemId);
			if (seq !== loadSeq) return;
			system = detail;
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

	const isOwner = $derived(!!auth.user && !!system && system.owner?.id === auth.user.id);

	$effect(() => {
		const id = page.params.id;
		if (id) load(id);
	});
</script>

<svelte:head><title>{system ? `Definitions · ${system.name}` : 'Definitions'} — Edifyce</title></svelte:head>

<PageContainer maxWidth="3xl" gap>
	<BackLink href={`/systems/${page.params.id}`} label="Back to system" />

	{#if error}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>System unavailable</Alert.Title>
			<Alert.Description>{error}</Alert.Description>
		</Alert.Root>
	{:else if loading || !system}
		<LoadingSpinner message="Loading definitions…" />
	{:else if system}
		<EntityHeader title="Definitions" subtitle={system.name}>
			{#snippet actions()}
				{#if isOwner}
					<Button href={`/systems/${system?.id}/edit`} variant="outline" size="sm">
						<Pencil class="size-4" /> Edit in system
					</Button>
				{/if}
			{/snippet}
		</EntityHeader>

		{#if system.definitions.length === 0}
			<SectionCard variant="muted">
				<p class="text-sm text-muted-foreground">
					This system has no definitions yet.{#if isOwner}
						<a class="underline" href={`/systems/${system.id}/edit`}>Add one in the editor</a>.{/if}
				</p>
			</SectionCard>
		{:else}
			<ul class="flex flex-col gap-2">
				{#each system.definitions as def (def.id)}
					<li>
						<a
							href={`/systems/${system.id}/definitions/${def.id}`}
							class="flex items-center justify-between gap-3 rounded-lg border p-3 hover:bg-muted/40"
						>
							<div class="min-w-0">
								<div class="text-sm font-medium">{def.name}</div>
								<div class="truncate font-mono text-xs text-muted-foreground">
									{def.higher} ≝ {def.lower}
								</div>
							</div>
							<div class="flex shrink-0 gap-1">
								{#if def.fresh.length > 0}
									<Badge variant="secondary" class="text-xs">fresh</Badge>
								{/if}
								{#if def.provisos.length > 0}
									<Badge variant="secondary" class="text-xs">
										{def.provisos.length}
										{def.provisos.length === 1 ? 'proviso' : 'provisos'}
									</Badge>
								{/if}
							</div>
						</a>
					</li>
				{/each}
			</ul>
		{/if}

		<Button href={`/systems/${system.id}`} variant="ghost" size="sm" class="self-start">
			<Layers class="size-4" /> View full system
		</Button>
	{/if}
</PageContainer>
