<script lang="ts" generics="TData">
	import {
		type ColumnDef,
		type SortingState,
		type ColumnFiltersState,
		type PaginationState,
		getCoreRowModel,
		getSortedRowModel,
		getFilteredRowModel,
		getPaginationRowModel
	} from '@tanstack/table-core';
	import { createSvelteTable } from './create-svelte-table.svelte.js';
	import FlexRender from './flex-render.svelte';
	import * as Table from '$lib/components/ui/table';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { cn } from '$lib/utils';
	import { untrack } from 'svelte';
	import Search from '@lucide/svelte/icons/search';
	import ArrowUpDown from '@lucide/svelte/icons/arrow-up-down';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import ArrowDown from '@lucide/svelte/icons/arrow-down';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import ChevronsLeft from '@lucide/svelte/icons/chevrons-left';
	import ChevronsRight from '@lucide/svelte/icons/chevrons-right';
	import type { Snippet } from 'svelte';

	/**
	 * Server-side pagination config. When provided, the DataTable delegates
	 * pagination, sorting, and search to the server — it won't filter or
	 * paginate client-side. The parent must supply `data` (current page),
	 * `totalCount`, and react to the `onpagechange` callback to fetch the
	 * next page.
	 */
	type ServerSideConfig = {
		/** Total number of rows across all pages (for page count calculation). */
		totalCount: number;
		/** Fired when the user navigates pages. The parent should re-fetch data. */
		onpagechange: (pageIndex: number, pageSize: number) => void;
		/** Fired when the user types in the search box (debounce is the parent's job). */
		onsearch?: (value: string) => void;
		/** Fired when sorting changes. */
		onsortingchange?: (sorting: SortingState) => void;
		/** Whether a fetch is currently in flight (shows loading indicator). */
		loading?: boolean;
	};

	type Props = {
		data: TData[];
		columns: ColumnDef<TData, unknown>[];
		searchPlaceholder?: string;
		searchColumn?: string;
		globalSearch?: boolean;
		pageSize?: number;
		class?: string;
		toolbar?: Snippet;
		emptyMessage?: string;
		borderless?: boolean;
		tableFixed?: boolean;
		onrowclick?: (row: TData, event?: MouseEvent) => void;
		/** Opt into server-side pagination/search/sorting. */
		serverSide?: ServerSideConfig;
	};

	let {
		data,
		columns,
		searchPlaceholder = 'Search…',
		searchColumn,
		globalSearch = false,
		pageSize = 10,
		class: className,
		toolbar,
		emptyMessage = 'No results.',
		borderless = false,
		tableFixed = false,
		onrowclick,
		serverSide
	}: Props = $props();

	let sorting = $state<SortingState>([]);
	let columnFilters = $state<ColumnFiltersState>([]);
	let globalFilter = $state('');
	// `pageSize` seeds the initial page size only; the table owns it afterwards.
	let pagination = $state<PaginationState>({ pageIndex: 0, pageSize: untrack(() => pageSize) });
	let wrapperEl: HTMLDivElement | undefined;

	function resetPage() {
		pagination = { ...pagination, pageIndex: 0 };
	}

	const tableInstance = createSvelteTable({
		get data() {
			return data;
		},
		get columns() {
			return columns;
		},
		// In server-side mode, tell TanStack the total row count so it computes
		// page count correctly even though `data` only contains one page.
		get rowCount() {
			return serverSide ? serverSide.totalCount : undefined;
		},
		// In server-side mode, disable all client-side processing.
		get manualPagination() {
			return !!serverSide;
		},
		get manualFiltering() {
			return !!serverSide;
		},
		get manualSorting() {
			return !!serverSide;
		},
		state: {
			get sorting() {
				return sorting;
			},
			get columnFilters() {
				return columnFilters;
			},
			get globalFilter() {
				return globalFilter;
			},
			get pagination() {
				return pagination;
			}
		},
		onSortingChange: (updater) => {
			sorting = typeof updater === 'function' ? updater(sorting) : updater;
			if (serverSide) {
				resetPage();
				serverSide.onsortingchange?.(sorting);
				serverSide.onpagechange(0, pagination.pageSize);
			}
		},
		onColumnFiltersChange: (updater) => {
			columnFilters = typeof updater === 'function' ? updater(columnFilters) : updater;
			resetPage();
		},
		onGlobalFilterChange: (updater) => {
			globalFilter = typeof updater === 'function' ? updater(globalFilter) : updater;
			resetPage();
		},
		onPaginationChange: (updater) => {
			const prev = pagination;
			pagination = typeof updater === 'function' ? updater(pagination) : updater;
			if (
				serverSide &&
				(pagination.pageIndex !== prev.pageIndex || pagination.pageSize !== prev.pageSize)
			) {
				serverSide.onpagechange(pagination.pageIndex, pagination.pageSize);
			}
			// Scroll to the top of the table's scroll container when changing pages.
			// We avoid scrollIntoView because it traverses ALL scrollable ancestors,
			// which can trigger the document to scroll and create double scrollbars.
			requestAnimationFrame(() => {
				if (!wrapperEl) return;
				let el: HTMLElement | null = wrapperEl.parentElement;
				while (el) {
					const { overflowY } = getComputedStyle(el);
					if (overflowY === 'auto' || overflowY === 'scroll') {
						const rect = wrapperEl.getBoundingClientRect();
						const containerRect = el.getBoundingClientRect();
						if (rect.top < containerRect.top) {
							el.scrollTop -= containerRect.top - rect.top;
						}
						break;
					}
					el = el.parentElement;
				}
			});
		},
		getCoreRowModel: getCoreRowModel(),
		getSortedRowModel: getSortedRowModel(),
		getFilteredRowModel: getFilteredRowModel(),
		getPaginationRowModel: getPaginationRowModel()
	});

	const table = $derived(tableInstance.table);

	// NOTE: table is a mutable TanStack instance — $derived returns the same reference
	// each time, so Svelte 5's Object.is equality check sees it as "unchanged" and won't
	// propagate to dependent deriveds. We must explicitly read the $state variables that
	// affect each derived value so they re-evaluate when state actually changes.

	const rows = $derived.by(() => {
		void data;
		void pagination;
		void sorting;
		void columnFilters;
		void globalFilter;
		return table.getRowModel().rows;
	});
	const filteredCount = $derived.by(() => {
		if (serverSide) return serverSide.totalCount;
		void data;
		void columnFilters;
		void globalFilter;
		return table.getFilteredRowModel().rows.length;
	});
	const totalCount = $derived(serverSide ? serverSide.totalCount : data.length);
	const pageCount = $derived.by(() => {
		void data;
		void pagination;
		void columnFilters;
		void globalFilter;
		return table.getPageCount();
	});
	const currentPage = $derived.by(() => {
		void pagination;
		return table.getState().pagination.pageIndex;
	});

	// Header groups also need explicit sorting dep to re-render sort indicators
	const headerGroups = $derived.by(() => {
		void sorting;
		return table.getHeaderGroups();
	});

	const canPreviousPage = $derived.by(() => {
		void pagination;
		return table.getCanPreviousPage();
	});
	const canNextPage = $derived.by(() => {
		void data;
		void pagination;
		void columnFilters;
		void globalFilter;
		return table.getCanNextPage();
	});

	const showPagination = $derived(totalCount > pageSize);
	const showSearch = $derived(totalCount > 5 || searchColumn != null || globalSearch);

	// Debounce timer for server-side search
	let searchTimer: ReturnType<typeof setTimeout> | undefined;

	function handleSearch(value: string) {
		if (serverSide?.onsearch) {
			globalFilter = value;
			clearTimeout(searchTimer);
			searchTimer = setTimeout(() => {
				resetPage();
				serverSide!.onsearch!(value);
				serverSide!.onpagechange(0, pagination.pageSize);
			}, 300);
		} else if (globalSearch) {
			globalFilter = value;
		} else if (searchColumn) {
			table.getColumn(searchColumn)?.setFilterValue(value);
			resetPage();
		}
	}

	const searchValue = $derived(
		globalSearch || serverSide?.onsearch
			? globalFilter
			: (((searchColumn ? table.getColumn(searchColumn)?.getFilterValue() : '') as string) ?? '')
	);
</script>

<div bind:this={wrapperEl} class={cn('space-y-3', className)}>
	{#if showSearch || toolbar}
		<div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
			{#if showSearch}
				<div class="relative max-w-sm">
					<Search class="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
					<Input
						type="search"
						placeholder={searchPlaceholder}
						class="pl-9"
						value={searchValue}
						oninput={(e) => handleSearch(e.currentTarget.value)}
					/>
				</div>
			{/if}
			{#if toolbar}
				<div class="flex shrink-0 items-center gap-2">
					{@render toolbar()}
				</div>
			{/if}
		</div>
	{/if}

	<div class={cn(!borderless && 'rounded-md border', serverSide?.loading && 'opacity-60')}>
		<Table.Root class={tableFixed ? 'table-fixed' : ''}>
			<Table.Header>
				{#each headerGroups as headerGroup (headerGroup.id)}
					<Table.Row>
						{#each headerGroup.headers as header (header.id)}
							<Table.Head class={header.column.columnDef.meta?.headerClass}>
								{#if !header.isPlaceholder}
									{#if header.column.getCanSort()}
										<button
											type="button"
											class="-ml-3 inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md px-3 text-xs font-medium hover:bg-accent hover:text-accent-foreground"
											onclick={header.column.getToggleSortingHandler()}
										>
											<FlexRender
												content={header.column.columnDef.header}
												context={header.getContext()}
											/>
											{#if header.column.getIsSorted() === 'asc'}
												<ArrowUp class="h-3.5 w-3.5" />
											{:else if header.column.getIsSorted() === 'desc'}
												<ArrowDown class="h-3.5 w-3.5" />
											{:else}
												<ArrowUpDown class="h-3.5 w-3.5 text-muted-foreground/50" />
											{/if}
										</button>
									{:else}
										<FlexRender
											content={header.column.columnDef.header}
											context={header.getContext()}
										/>
									{/if}
								{/if}
							</Table.Head>
						{/each}
					</Table.Row>
				{/each}
			</Table.Header>
			<Table.Body>
				{#if rows.length === 0}
					<Table.Row>
						<Table.Cell colspan={columns.length} class="h-24 text-center text-muted-foreground">
							{emptyMessage}
						</Table.Cell>
					</Table.Row>
				{:else}
					{#each rows as row (row.id)}
						<Table.Row
							onclick={onrowclick ? (e: MouseEvent) => onrowclick!(row.original, e) : undefined}
							class={onrowclick ? 'cursor-pointer' : undefined}
						>
							{#each row.getVisibleCells() as cell (cell.id)}
								<Table.Cell class={cell.column.columnDef.meta?.cellClass}>
									<FlexRender content={cell.column.columnDef.cell} context={cell.getContext()} />
								</Table.Cell>
							{/each}
						</Table.Row>
					{/each}
				{/if}
			</Table.Body>
		</Table.Root>
	</div>

	{#if showPagination || filteredCount !== totalCount}
		<div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
			<p class="text-xs text-muted-foreground">
				{#if filteredCount !== totalCount}
					{filteredCount} of {totalCount} results
				{:else}
					{totalCount} results
				{/if}
			</p>
			{#if showPagination && pageCount > 1}
				<div class="flex items-center gap-1">
					<Button
						variant="outline"
						size="icon"
						class="h-8 w-8"
						disabled={!canPreviousPage || serverSide?.loading}
						onclick={() => table.setPageIndex(0)}
					>
						<ChevronsLeft class="h-4 w-4" />
						<span class="sr-only">First page</span>
					</Button>
					<Button
						variant="outline"
						size="icon"
						class="h-8 w-8"
						disabled={!canPreviousPage || serverSide?.loading}
						onclick={() => table.previousPage()}
					>
						<ChevronLeft class="h-4 w-4" />
						<span class="sr-only">Previous page</span>
					</Button>
					<span class="px-2 text-xs text-muted-foreground">
						{currentPage + 1} / {pageCount}
					</span>
					<Button
						variant="outline"
						size="icon"
						class="h-8 w-8"
						disabled={!canNextPage || serverSide?.loading}
						onclick={() => table.nextPage()}
					>
						<ChevronRight class="h-4 w-4" />
						<span class="sr-only">Next page</span>
					</Button>
					<Button
						variant="outline"
						size="icon"
						class="h-8 w-8"
						disabled={!canNextPage || serverSide?.loading}
						onclick={() => table.setPageIndex(pageCount - 1)}
					>
						<ChevronsRight class="h-4 w-4" />
						<span class="sr-only">Last page</span>
					</Button>
				</div>
			{/if}
		</div>
	{/if}
</div>
