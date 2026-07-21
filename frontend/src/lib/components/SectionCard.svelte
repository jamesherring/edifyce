<script lang="ts">
  import { cn } from '$lib/utils';
  import type { Snippet } from 'svelte';

  type Props = {
    title?: string;
    variant?: 'default' | 'muted';
    children: Snippet;
    class?: string;
  };

  let { title, variant = 'default', children, class: className }: Props = $props();
</script>

<div
  class={cn('rounded-lg border p-4', variant === 'muted' && 'border-muted bg-muted/30', className)}
>
  {#if title}
    <h2 class="mb-3 text-sm font-medium">{title}</h2>
  {/if}
  {@render children()}
</div>
