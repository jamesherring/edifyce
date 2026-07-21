import type { Component } from 'svelte';
import type { Snippet } from 'svelte';

type RenderComponentConfig<TProps extends Record<string, unknown>> = {
  component: Component<TProps>;
  props: TProps;
};

type RenderSnippetConfig<TProps> = {
  snippet: Snippet<[TProps]>;
  params: TProps;
};

/**
 * Wraps a Svelte component for use in TanStack Table column definitions.
 * Usage: `cell: ({ row }) => renderComponent(MyCell, { value: row.original.name })`
 */
export function renderComponent<TProps extends Record<string, unknown>>(
  component: Component<TProps>,
  props: TProps
): RenderComponentConfig<TProps> {
  return { component, props };
}

/**
 * Wraps a Svelte snippet for use in TanStack Table column definitions.
 * Usage: `cell: ({ row }) => renderSnippet(mySnippet, row.original)`
 */
export function renderSnippet<TProps>(
  snippet: Snippet<[TProps]>,
  params: TProps
): RenderSnippetConfig<TProps> {
  return { snippet, params };
}
