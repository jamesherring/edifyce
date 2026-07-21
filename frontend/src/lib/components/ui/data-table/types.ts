import '@tanstack/table-core';

declare module '@tanstack/table-core' {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData, TValue> {
    headerClass?: string;
    cellClass?: string;
  }
}
