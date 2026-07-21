<script lang="ts">
  import type { Component, Snippet } from 'svelte';

  type Props = {
    content: unknown;
    context?: unknown;
  };

  let { content, context }: Props = $props();
</script>

{#if typeof content === 'string'}
  {content}
{:else if typeof content === 'function'}
  {@const result = (content as (ctx: unknown) => unknown)(context)}
  {#if result && typeof result === 'object' && 'component' in result}
    {@const config = result as {
      component: Component<Record<string, unknown>>;
      props: Record<string, unknown>;
    }}
    <config.component {...config.props} />
  {:else if result && typeof result === 'object' && 'snippet' in result}
    {@const config = result as { snippet: Snippet<[unknown]>; params: unknown }}
    {@render config.snippet(config.params)}
  {:else if typeof result === 'string'}
    {result}
  {/if}
{/if}
