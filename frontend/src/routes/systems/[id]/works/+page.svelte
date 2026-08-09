<script lang="ts">
	import { page } from '$app/state';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import EntityHeader from '$lib/components/EntityHeader.svelte';
	import BackLink from '$lib/components/BackLink.svelte';
	import SectionCard from '$lib/components/SectionCard.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import { Badge } from '$lib/components/ui/badge';
	import * as Alert from '$lib/components/ui/alert';
	import { api, ApiError, type FormalSystemDetail, type WorkCited } from '$lib/api';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';

	let system = $state<FormalSystemDetail | null>(null);
	let works = $state<WorkCited[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let loadSeq = 0;

	async function load(systemId: string) {
		const seq = ++loadSeq;
		loading = true;
		error = null;
		try {
			const [detail, cited] = await Promise.all([
				api.systems.get(systemId),
				api.systems.works(systemId)
			]);
			if (seq !== loadSeq) return;
			system = detail;
			works = cited;
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
		if (id) load(id);
	});
</script>

<PageContainer maxWidth="3xl" gap>
	<BackLink href={`/systems/${page.params.id}`} label="Back to system" />

	{#if error}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>System unavailable</Alert.Title>
			<Alert.Description>{error}</Alert.Description>
		</Alert.Root>
	{:else if loading || !system}
		<LoadingSpinner message="Loading works cited…" />
	{:else}
		<EntityHeader title="Works cited" subtitle={system.name} />

		{#if works.length === 0}
			<SectionCard variant="muted">
				<p class="text-sm text-muted-foreground">
					This system's prose cites no outside literature. An imported corpus records its
					sources as bibliography keys in its comments; a system authored here has none
					unless someone writes them.
				</p>
			</SectionCard>
		{:else}
			<!-- Keys only, and deliberately: the bibliography they index lives outside
			     the `.mm` file, in whatever page its `$t` block names, so there is no
			     title or author to show. What the count buys is the shape of the
			     library — which sources it leans on, and how hard. -->
			<ul class="flex flex-col gap-2">
				{#each works as work (work.work)}
					<li>
						<a
							href={`/systems/${system.id}/works/${encodeURIComponent(work.work)}`}
							class="flex items-center justify-between gap-3 rounded-lg border p-3 hover:bg-muted/40"
						>
							<span class="min-w-0 truncate font-mono text-sm">{work.work}</span>
							<Badge variant="secondary" class="shrink-0 tabular-nums">
								{work.citations}
								{work.citations === 1 ? 'citation' : 'citations'}
							</Badge>
						</a>
					</li>
				{/each}
			</ul>
		{/if}
	{/if}
</PageContainer>
