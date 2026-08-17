<script lang="ts">
	import { goto } from '$app/navigation';
	import type { ColumnDef } from '@tanstack/table-core';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import CheckBadge from '$lib/components/CheckBadge.svelte';
	import { DataTable, renderComponent } from '$lib/components/ui/data-table';
	import * as Alert from '$lib/components/ui/alert';
	import { Button } from '$lib/components/ui/button';
	import { api, type ProofSummary } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { createPaginatedList } from '$lib/paged-list.svelte';
	import { timeAgo } from '$lib/format';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import Plus from '@lucide/svelte/icons/plus';

	const PAGE_SIZE = 10;

	// Server-side paging/search/sort lives in the shared controller; the page
	// supplies only the page size and which API call each view maps to.
	const list = createPaginatedList<ProofSummary>({
		pageSize: PAGE_SIZE,
		load: (view, params) =>
			view === 'mine' ? api.proofs.list(undefined, params) : api.proofs.listPublic(params)
	});

	const columns = $derived<ColumnDef<ProofSummary, unknown>[]>([
		{
			accessorKey: 'name',
			header: 'Name',
			cell: ({ getValue }) => getValue() as string,
			meta: { cellClass: 'font-medium' }
		},
		{
			id: 'about',
			header: 'Description',
			// Title first, description second. On an imported corpus `name` is an
			// opaque label (`sqrt2irr`) and the title is the only readable thing in
			// the row; a hand-authored proof usually has the description instead.
			accessorFn: (row) => row.title ?? row.description ?? '',
			cell: ({ row }) => row.original.title ?? row.original.description ?? '—',
			meta: { cellClass: 'hidden max-w-[24rem] truncate text-muted-foreground sm:table-cell' }
		},
		{
			id: 'author',
			header: 'Author',
			accessorFn: (row) => row.owner?.display_name ?? '',
			cell: ({ row }) => row.original.owner?.display_name ?? '—',
			meta: { cellClass: 'hidden text-muted-foreground md:table-cell' }
		},
		// Every row in the public view is published (and so verified), so the
		// verdict and status columns only earn their place in the owner's own list.
		...(list.view === 'mine'
			? [
					{
						id: 'checked',
						header: 'Checked',
						cell: ({ row }) => renderComponent(CheckBadge, { valid: row.original.valid }),
						meta: { cellClass: 'hidden sm:table-cell' }
					} satisfies ColumnDef<ProofSummary, unknown>,
					{
						id: 'status',
						header: 'Status',
						cell: ({ row }) =>
							renderComponent(StatusBadge, {
								status: row.original.published_at ? ('published' as const) : ('draft' as const)
							})
					} satisfies ColumnDef<ProofSummary, unknown>
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

<svelte:head><title>Proofs — Edifyce</title></svelte:head>

<PageContainer maxWidth="5xl">
	<PageHeader title="Proofs" description="Browse and verify machine-checked proofs.">
		{#snippet actions()}
			{#if auth.user}
				<div class="flex flex-wrap items-center gap-2">
					<div class="inline-flex rounded-md border p-0.5 text-sm">
						<button
							type="button"
							aria-pressed={list.view === 'public'}
							onclick={() => list.switchView('public')}
							class={[
								'rounded px-3 py-1 font-medium transition-colors',
								list.view === 'public'
									? 'bg-accent text-accent-foreground'
									: 'text-muted-foreground hover:text-foreground'
							]}
						>
							Published
						</button>
						<button
							type="button"
							aria-pressed={list.view === 'mine'}
							onclick={() => list.switchView('mine')}
							class={[
								'rounded px-3 py-1 font-medium transition-colors',
								list.view === 'mine'
									? 'bg-accent text-accent-foreground'
									: 'text-muted-foreground hover:text-foreground'
							]}
						>
							My proofs
						</button>
					</div>
					<Button href="/proofs/new" size="sm">
						<Plus class="size-4" /> New proof
					</Button>
				</div>
			{/if}
		{/snippet}
	</PageHeader>

	{#if list.error}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>Could not load proofs</Alert.Title>
			<Alert.Description>{list.error}</Alert.Description>
		</Alert.Root>
	{:else if list.loading && list.items.length === 0}
		<LoadingSpinner message="Loading proofs…" />
	{:else if list.total === 0 && !list.search}
		<!-- Genuinely nothing to show, as opposed to a search that matched nothing:
		     that keeps the table so the search can be changed. -->
		{#if list.view === 'mine'}
			<EmptyState
				title="No proofs yet"
				description="A proof is checked line by line against a formal system. Write one and watch it verify as you type."
				actionLabel="New proof"
				onAction={() => goto('/proofs/new')}
				secondaryActionLabel="Browse published"
				onSecondaryAction={() => list.switchView('public')}
			/>
		{:else}
			<EmptyState
				title="No published proofs yet"
				description="Nothing has been published for everyone to see. Proofs stay private until their author publishes them."
				actionLabel={auth.user ? 'New proof' : undefined}
				onAction={auth.user ? () => goto('/proofs/new') : undefined}
			/>
		{/if}
	{:else}
		<!-- Remount on view switch so the table's internal page/sort/search reset. -->
		{#key list.view}
			<DataTable
				data={list.items}
				{columns}
				pageSize={PAGE_SIZE}
				searchPlaceholder="Search proofs…"
				onrowclick={(row) => goto(`/proofs/${row.id}`)}
				serverSide={list.serverSide}
				emptyMessage={list.search
					? `No proofs match “${list.search}”.`
					: list.view === 'mine'
						? "You haven't written any proofs yet."
						: 'No published proofs yet.'}
			/>
		{/key}
	{/if}
</PageContainer>
