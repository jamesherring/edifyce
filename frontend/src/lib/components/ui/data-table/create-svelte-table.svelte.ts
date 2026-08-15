import {
  createTable,
  type RowData,
  type TableOptions,
  type TableOptionsResolved
} from '@tanstack/table-core';

/**
 * Creates a reactive TanStack Table instance for Svelte 5.
 * Uses $state internally so the returned table is reactive.
 */
export function createSvelteTable<TData extends RowData>(options: TableOptions<TData>) {
  const resolvedOptions: TableOptionsResolved<TData> = {
    state: {},
    onStateChange() {},
    renderFallbackValue: null,
    ...options
  };

  const table = createTable(resolvedOptions);

  let state = $state(table.initialState);

  function updateOptions(updatedOpts: TableOptions<TData>) {
    table.setOptions((prev) => ({
      ...prev,
      ...updatedOpts,
      state: {
        ...state,
        ...(updatedOpts.state ?? {})
      },
      onStateChange: (updater: unknown) => {
        if (typeof updater === 'function') {
          state = updater(state);
        } else {
          state = updater as typeof state;
        }
        updatedOpts.onStateChange?.(updater as never);
      }
    }));
  }

  updateOptions(options);

  return {
    get table() {
      updateOptions(options);
      return table;
    },
    get state() {
      return state;
    }
  };
}
