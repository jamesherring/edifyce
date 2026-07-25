import { untrack } from 'svelte';
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
	/** The active search term — empty when the user hasn't searched. Lets a page
	 *  tell "nothing here yet" from "nothing matched", which want different
	 *  empty states. */
	readonly search: string;
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

	function applyView(next: ListView): void {
		if (next === view) return;
		view = next;
		pageIndex = 0;
		search = '';
		sorting = [];
		// Clear the result set so the switch shows the spinner, not the previous
		// view's data under the (possibly different) new columns. `total` describes
		// the same result set as `items` and has to go with it, or an empty-state
		// check would read the old view's count.
		items = [];
		total = 0;
	}

	// Whether the user has picked a view for themselves. Not reactive on purpose:
	// it gates the default below without re-running it.
	let chosen = false;

	function switchView(next: ListView): void {
		chosen = true;
		applyView(next);
	}

	// Who you are decides which list you land on: a signed-in user's own rows are
	// what they came for, and the published list is for discovery. Once they've
	// picked a view themselves, that stands — except when signing out, where
	// staying on "mine" would 401 every fetch.
	$effect(() => {
		if (!auth.ready) return;
		const user = auth.user;
		// `applyView` reads `view`, which this effect only ever writes — tracking it
		// would re-run the effect on every switch to no purpose.
		untrack(() => {
			if (!user) applyView('public');
			else if (!chosen) applyView('mine');
		});
	});

	// Re-fetch on any view/page/search/sort change, but not before auth resolves:
	// until then we don't know which list this user should be looking at, and
	// fetching the wrong one costs a request and flashes the wrong rows.
	$effect(() => {
		void pageIndex;
		void search;
		void sorting;
		void view;
		if (!auth.ready) return;
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
		get search() {
			return search;
		},
		serverSide,
		switchView
	};
}
