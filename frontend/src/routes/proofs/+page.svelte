<script lang="ts">
	import { goto } from '$app/navigation';
	import type { ColumnDef, SortingState } from '@tanstack/table-core';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import CheckBadge from '$lib/components/CheckBadge.svelte';
	import { DataTable, renderComponent } from '$lib/components/ui/data-table';
	import * as Alert from '$lib/components/ui/alert';
	import { Button } from '$lib/components/ui/button';
	import { api, ApiError, type ProofSummary } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { timeAgo } from '$lib/format';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import Plus from '@lucide/svelte/icons/plus';

	// 'public' = the shared master list (published only); 'mine' = the signed-in
	// user's own proofs, drafts included.
	type View = 'public' | 'mine';
	let view = $state<View>('public');

	const PAGE_SIZE = 10;

	let proofs = $state<ProofSummary[]>([]);
	let total = $state(0);
	let loading = $state(true);
	let error = $state<string | null>(null);

	// Pagination/search/sort state — the source of truth the DataTable delegates
	// to in server-side mode. The fetch effect below reacts to all of them.
	let pageIndex = $state(0);
	let pageSize = $state(PAGE_SIZE);
	let search = $state('');
	let sorting = $state<SortingState>([]);

	// Guard against out-of-order responses: a fast toggle can leave an older
	// request resolving last and clobbering the newer view's data.
	let requestSeq = 0;

	async function fetchProofs(current: View) {
		const seq = ++requestSeq;
		loading = true;
		error = null;
		const params = {
			limit: pageSize,
			offset: pageIndex * pageSize,
			search: search || undefined,
			sort: sorting[0]?.id,
			desc: sorting[0]?.desc ?? false
		};
		try {
			const result =
				current === 'mine'
					? await api.proofs.list(undefined, params)
					: await api.proofs.listPublic(params);
			if (seq !== requestSeq) return;
			proofs = result.items;
			total = result.total;
		} catch (err) {
			if (seq !== requestSeq) return;
			error = err instanceof ApiError ? err.message : String(err);
			proofs = [];
			total = 0;
		} finally {
			if (seq === requestSeq) loading = false;
		}
	}

	// Switching views starts a fresh query; the `{#key view}` block below remounts
	// the DataTable so its internal page/sort/search reset to match.
	function switchView(next: View) {
		if (next === view) return;
		view = next;
		pageIndex = 0;
		search = '';
		sorting = [];
		// Clear the current rows so the switch shows the spinner, not the previous
		// view's data under the (possibly different) new columns.
		proofs = [];
		total = 0;
	}

	// Logging out while on "My proofs" would otherwise leave view='mine' and the
	// next fetch 401s; fall back to the public list.
	$effect(() => {
		if (auth.ready && !auth.user && view === 'mine') switchView('public');
	});

	// Re-fetch whenever the view or any pagination/search/sort input changes. Only
	// 'mine' depends on auth resolving.
	$effect(() => {
		void pageIndex;
		void pageSize;
		void search;
		void sorting;
		const current = view;
		if (current === 'mine') void auth.ready;
		fetchProofs(current);
	});

	// The DataTable owns its page/sort/search UI and hands changes back here.
	const serverSide = {
		get totalCount() {
			return total;
		},
		get loading() {
			return loading;
		},
		onpagechange: (pi: number, ps: number) => {
			pageIndex = pi;
			pageSize = ps;
		},
		onsearch: (value: string) => {
			search = value;
		},
		onsortingchange: (next: SortingState) => {
			sorting = next;
		}
	};

	const columns = $derived<ColumnDef<ProofSummary, unknown>[]>([
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
		// Every row in the public view is published (and so verified), so the
		// verdict and status columns only earn their place in the owner's own list.
		...(view === 'mine'
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

<PageContainer maxWidth="5xl">
	<PageHeader title="Proofs" description="Browse and verify machine-checked proofs.">
		{#snippet actions()}
			{#if auth.user}
				<div class="flex flex-wrap items-center gap-2">
					<div class="inline-flex rounded-md border p-0.5 text-sm">
						<button
							type="button"
							onclick={() => switchView('public')}
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
							onclick={() => switchView('mine')}
							class={[
								'rounded px-3 py-1 font-medium transition-colors',
								view === 'mine'
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

	{#if error}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>Could not load proofs</Alert.Title>
			<Alert.Description>{error}</Alert.Description>
		</Alert.Root>
	{:else if loading && proofs.length === 0}
		<LoadingSpinner message="Loading proofs…" />
	{:else}
		<!-- Remount on view switch so the table's internal page/sort/search reset. -->
		{#key view}
			<DataTable
				data={proofs}
				{columns}
				pageSize={PAGE_SIZE}
				searchPlaceholder="Search proofs…"
				onrowclick={(row) => goto(`/proofs/${row.id}`)}
				{serverSide}
				emptyMessage={view === 'mine'
					? "You haven't written any proofs yet."
					: 'No published proofs yet.'}
			/>
		{/key}
	{/if}
</PageContainer>
