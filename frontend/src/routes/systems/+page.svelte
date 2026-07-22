<script lang="ts">
	import { goto } from '$app/navigation';
	import type { ColumnDef } from '@tanstack/table-core';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import { DataTable, renderComponent } from '$lib/components/ui/data-table';
	import * as Alert from '$lib/components/ui/alert';
	import { Button } from '$lib/components/ui/button';
	import { api, ApiError, type FormalSystemSummary } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { timeAgo } from '$lib/format';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import Plus from '@lucide/svelte/icons/plus';

	// 'public' = the shared master list (published only); 'mine' = the signed-in
	// user's own systems, drafts included.
	type View = 'public' | 'mine';
	let view = $state<View>('public');

	let systems = $state<FormalSystemSummary[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);

	// Guard against out-of-order responses: a fast toggle can leave an older
	// request resolving last and clobbering the newer view's data.
	let requestSeq = 0;

	async function fetchSystems(current: View) {
		const seq = ++requestSeq;
		loading = true;
		error = null;
		try {
			const result =
				current === 'mine' ? await api.systems.list() : await api.systems.listPublic();
			if (seq !== requestSeq) return;
			systems = result;
		} catch (err) {
			if (seq !== requestSeq) return;
			error = err instanceof ApiError ? err.message : String(err);
			systems = [];
		} finally {
			if (seq === requestSeq) loading = false;
		}
	}

	// Logging out while on "My systems" would otherwise leave view='mine' and the
	// next fetch 401s; fall back to the public list.
	$effect(() => {
		if (auth.ready && !auth.user && view === 'mine') view = 'public';
	});

	// Re-fetch when the view changes. Only 'mine' depends on auth resolving (it's
	// the authenticated call); reading auth.ready only in that branch keeps the
	// public list from re-fetching a second time when auth flips.
	$effect(() => {
		const current = view;
		if (current === 'mine') void auth.ready;
		fetchSystems(current);
	});

	const columns = $derived<ColumnDef<FormalSystemSummary, unknown>[]>([
		{
			accessorKey: 'name',
			header: 'Name',
			cell: ({ getValue }) => getValue() as string,
			meta: { cellClass: 'font-medium' }
		},
		{
			accessorKey: 'description',
			header: 'Description',
			cell: ({ getValue }) => (getValue() as string | null) ?? '—',
			meta: { cellClass: 'hidden max-w-[24rem] truncate text-muted-foreground sm:table-cell' }
		},
		{
			id: 'author',
			header: 'Author',
			accessorFn: (row) => row.owner?.display_name ?? '',
			cell: ({ row }) => row.original.owner?.display_name ?? '—',
			meta: { cellClass: 'hidden text-muted-foreground md:table-cell' }
		},
		// Every row in the public view is published, so the status column only
		// earns its place in the owner's own list.
		...(view === 'mine'
			? [
					{
						id: 'status',
						header: 'Status',
						cell: ({ row }) =>
							renderComponent(StatusBadge, {
								status: row.original.published_at ? ('published' as const) : ('draft' as const)
							})
					} satisfies ColumnDef<FormalSystemSummary, unknown>
				]
			: []),
		{
			accessorKey: 'updated_at',
			header: 'Updated',
			cell: ({ getValue }) => timeAgo(getValue() as string),
			meta: { cellClass: 'hidden text-muted-foreground sm:table-cell' }
		}
	]);
</script>

<PageContainer maxWidth="5xl">
	<PageHeader title="Formal systems" description="Browse and explore mechanically-checked formal systems.">
		{#snippet actions()}
			{#if auth.user}
				<div class="flex flex-wrap items-center gap-2">
					<div class="inline-flex rounded-md border p-0.5 text-sm">
						<button
							type="button"
							onclick={() => (view = 'public')}
							class={[
								'rounded px-3 py-1 font-medium transition-colors',
								view === 'public'
									? 'bg-accent text-accent-foreground'
									: 'text-muted-foreground hover:text-foreground'
							]}
						>
							Published
						</button>
						<button
							type="button"
							onclick={() => (view = 'mine')}
							class={[
								'rounded px-3 py-1 font-medium transition-colors',
								view === 'mine'
									? 'bg-accent text-accent-foreground'
									: 'text-muted-foreground hover:text-foreground'
							]}
						>
							My systems
						</button>
					</div>
					<Button href="/systems/new" size="sm">
						<Plus class="size-4" /> New system
					</Button>
				</div>
			{/if}
		{/snippet}
	</PageHeader>

	{#if error}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>Could not load systems</Alert.Title>
			<Alert.Description>{error}</Alert.Description>
		</Alert.Root>
	{:else if loading}
		<LoadingSpinner message="Loading systems…" />
	{:else}
		<DataTable
			data={systems}
			{columns}
			globalSearch
			searchPlaceholder="Search systems…"
			onrowclick={(row) => goto(`/systems/${row.id}`)}
			emptyMessage={view === 'mine'
				? "You haven't created any systems yet."
				: 'No published systems yet.'}
		/>
	{/if}
</PageContainer>
