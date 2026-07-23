import type { SortingState } from '@tanstack/table-core';
import { ApiError, type ListParams, type Page } from '$lib/api';
import { auth } from '$lib/auth.svelte';
import type { ServerSideConfig } from '$lib/components/ui/data-table';

/**
 * The two shared master lists a list page can show: `public` = every published
 * row (any owner, no auth); `mine` = the signed-in user's own rows, drafts
 * included. Only `mine` depends on auth.
 */
export type ListView = 'public' | 'mine';

export interface PaginatedList<T> {
	readonly items: T[];
	readonly total: number;
	readonly loading: boolean;
	readonly error: string | null;
	readonly view: ListView;
	/** Hand straight to `<DataTable serverSide={…} />`. */
	readonly serverSide: ServerSideConfig;
	/** Switch master list, resetting page/search/sort. */
	switchView(next: ListView): void;
}

/**
 * The server-side paging/search/sort controller both the systems and proofs list
 * pages share. It owns the view + pagination state, drives the fetch (with an
 * out-of-order guard), and exposes a ready-made `serverSide` config for the
 * DataTable. Each page supplies only what differs: the page size and a `load`
 * thunk that maps `(view, params)` to the right API call.
 *
 * Mirrors the `createSectionController` / `createAuth` factory pattern — call it
 * once at component init (its `$effect`s attach to that component).
 */
export function createPaginatedList<T>(opts: {
	pageSize: number;
	load: (view: ListView, params: ListParams) => Promise<Page<T>>;
}): PaginatedList<T> {
	let items = $state<T[]>([]);
	let total = $state(0);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let view = $state<ListView>('public');
	let pageIndex = $state(0);
	let search = $state('');
	let sorting = $state<SortingState>([]);

	// Monotonic id of the most recent fetch: a fast toggle can leave an older
	// request resolving last, and only the latest may write the results.
	let latestOp = 0;

	async function fetchPage(): Promise<void> {
		const op = ++latestOp;
		loading = true;
		error = null;
		const current = view;
		const params: ListParams = {
			limit: opts.pageSize,
			offset: pageIndex * opts.pageSize,
			search: search || undefined,
			sort: sorting[0]?.id,
			desc: sorting[0]?.desc ?? false
		};
		try {
			const result = await opts.load(current, params);
			if (op !== latestOp) return;
			items = result.items;
			total = result.total;
		} catch (err) {
			if (op !== latestOp) return;
			error = err instanceof ApiError ? err.message : String(err);
			items = [];
		} finally {
			if (op === latestOp) loading = false;
		}
	}

	function switchView(next: ListView): void {
		if (next === view) return;
		view = next;
		pageIndex = 0;
		search = '';
		sorting = [];
		// Clear the rows so the switch shows the spinner, not the previous view's
		// data under the (possibly different) new columns.
		items = [];
	}

	// Logging out while on "mine" would leave the next fetch 401ing; fall back to
	// the public list.
	$effect(() => {
		if (auth.ready && !auth.user && view === 'mine') switchView('public');
	});

	// Re-fetch on any view/page/search/sort change. Only 'mine' depends on auth
	// resolving; reading auth.ready only in that branch keeps the public list from
	// re-fetching a second time when auth flips.
	$effect(() => {
		void pageIndex;
		void search;
		void sorting;
		const current = view;
		if (current === 'mine') void auth.ready;
		fetchPage();
	});

	const serverSide: ServerSideConfig = {
		get totalCount() {
			return total;
		},
		get loading() {
			return loading;
		},
		onpagechange: (pi: number) => {
			pageIndex = pi;
		},
		onsearch: (value: string) => {
			search = value;
		},
		onsortingchange: (next: SortingState) => {
			sorting = next;
		}
	};

	return {
		get items() {
			return items;
		},
		get total() {
			return total;
		},
		get loading() {
			return loading;
		},
		get error() {
			return error;
		},
		get view() {
			return view;
		},
		serverSide,
		switchView
	};
}
