<script lang="ts">
  import { cn } from '$lib/utils';
  import type { Snippet } from 'svelte';

  type Props = {
    title?: string;
    /** Anchor target, for in-page links to this card. */
    id?: string;
    variant?: 'default' | 'muted';
    children: Snippet;
    class?: string;
  };

  let { title, id, variant = 'default', children, class: className }: Props = $props();
</script>

<div
  {id}
  class={cn('rounded-lg border p-4', variant === 'muted' && 'border-muted bg-muted/30', className)}
>
  {#if title}
    <h2 class="mb-3 text-sm font-medium">{title}</h2>
  {/if}
  {@render children()}
</div>
