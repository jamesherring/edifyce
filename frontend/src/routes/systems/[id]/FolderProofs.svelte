<script lang="ts">
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import { Button } from '$lib/components/ui/button';
	import { api, ApiError, type Folder, type ProofSummary } from '$lib/api';

	const PAGE_SIZE = 25;

	let { systemId, folder }: { systemId: string; folder: Folder } = $props();

	let proofs = $state<ProofSummary[]>([]);
	let total = $state(0);
	// True from the start: the first fetch is queued by the effect below, which
	// runs after this render, so a `false` here paints "nothing in this section"
	// for a frame over a section that has plenty.
	let loading = $state(true);
	let error = $state<string | null>(null);

	// Monotonic, so a slow page for a folder the reader has since left cannot
	// append its rows under the folder they are now looking at.
	let latest = 0;

	async function fetchPage(offset: number): Promise<void> {
		const op = ++latest;
		loading = true;
		error = null;
		try {
			const page = await api.proofs.listPublic(
				{ limit: PAGE_SIZE, offset },
				{ formalSystemId: systemId, folderId: folder.id }
			);
			if (op !== latest) return;
			proofs = offset === 0 ? page.items : [...proofs, ...page.items];
			total = page.total;
		} catch (err) {
			if (op !== latest) return;
			error = err instanceof ApiError ? err.message : String(err);
		} finally {
			if (op === latest) loading = false;
		}
	}

	// Restart whenever the selected folder changes — including the first render.
	$effect(() => {
		void folder.id;
		proofs = [];
		total = 0;
		fetchPage(0);
	});
</script>

<div class="rounded-md border">
	<div class="flex items-baseline justify-between gap-2 border-b px-3 py-2">
		<h3 class="text-sm font-medium">{folder.name}</h3>
		<span class="shrink-0 text-xs text-muted-foreground">
			{total}
			{total === 1 ? 'proof' : 'proofs'}
		</span>
	</div>

	<!-- Beside the rows rather than in place of them: a failed *later* page must
	     not throw away the pages that arrived, since the only way back to them
	     would be to reselect the folder. -->
	{#if error}
		<p class="border-b px-3 py-2 text-sm text-destructive">{error}</p>
	{/if}

	{#if loading && proofs.length === 0}
		<LoadingSpinner message="Loading proofs…" />
	{:else if proofs.length === 0}
		<!-- The outline's count and this listing agree only where they ask the same
		     question. They do for an imported corpus — ownerless, so every count is
		     of published proofs — but a signed-in owner's count includes their own
		     drafts, which this omits. So this says what it found, not why. -->
		{#if !error}
			<p class="px-3 py-2 text-sm text-muted-foreground">
				Nothing published in this section.
			</p>
		{/if}
	{:else}
		<ul class="divide-y">
			{#each proofs as proof (proof.id)}
				<li>
					<a
						href={`/proofs/${proof.id}`}
						class="flex items-baseline gap-3 px-3 py-1.5 hover:bg-accent/50"
					>
						<!-- The label first and monospaced: on an imported corpus it is what a
						     citation has to spell, and the title is the readable half. -->
						<span class="shrink-0 font-mono text-xs">{proof.name}</span>
						{#if proof.title}
							<span class="truncate text-xs text-muted-foreground">{proof.title}</span>
						{/if}
					</a>
				</li>
			{/each}
		</ul>
		{#if proofs.length < total}
			<div class="border-t px-3 py-2">
				<Button variant="outline" size="sm" disabled={loading} onclick={() => fetchPage(proofs.length)}>
					{loading ? 'Loading…' : `Show more (${total - proofs.length} left)`}
				</Button>
			</div>
		{/if}
	{/if}
</div>
