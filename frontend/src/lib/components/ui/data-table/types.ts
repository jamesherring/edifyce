import '@tanstack/table-core';
import type { SortingState } from '@tanstack/table-core';

declare module '@tanstack/table-core' {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData, TValue> {
    headerClass?: string;
    cellClass?: string;
  }
}

/**
 * Server-side pagination config for `DataTable`. When provided, the table
 * delegates pagination, sorting, and search to the server — it won't filter or
 * paginate client-side. The parent supplies `data` (the current page) and
 * `totalCount`, and reacts to the callbacks to re-fetch.
 */
export interface ServerSideConfig {
  /** Total number of rows across all pages (for page-count calculation). */
  totalCount: number;
  /** Fired when the user navigates pages. The parent should re-fetch data. */
  onpagechange: (pageIndex: number, pageSize: number) => void;
  /** Fired when the user types in the search box (debounce is the parent's job). */
  onsearch?: (value: string) => void;
  /** Fired when sorting changes. */
  onsortingchange?: (sorting: SortingState) => void;
  /** Whether a fetch is currently in flight (shows a loading indicator). */
  loading?: boolean;
}
