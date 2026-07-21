<script lang="ts">
  import { cn } from '$lib/utils';
  import { timeAgo, formatDate } from '$lib/format';
  import type { Snippet } from 'svelte';

  type Props = {
    id?: string;
    createdAt?: string;
    formatAs?: 'relative' | 'absolute';
    items?: Snippet;
    class?: string;
  };

  let { id, createdAt, formatAs = 'relative', items, class: className }: Props = $props();
</script>

<div class={cn('flex items-center gap-4 font-mono text-xs text-muted-foreground', className)}>
  {#if id}
    <span>{id}</span>
  {/if}
  {#if createdAt}
    <span>Created {formatAs === 'relative' ? timeAgo(createdAt) : formatDate(createdAt)}</span>
  {/if}
  {#if items}
    {@render items()}
  {/if}
</div>
