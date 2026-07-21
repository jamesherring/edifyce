<script lang="ts">
  import { cn } from '$lib/utils';
  import type { Snippet } from 'svelte';

  type Props = {
    columns?: 2 | 3 | 4;
    gap?: 'sm' | 'default';
    class?: string;
    children: Snippet;
  };

  let { columns = 3, gap = 'default', class: className, children }: Props = $props();

  const colClass = $derived.by(() => {
    switch (columns) {
      case 2:
        return 'grid grid-cols-1 sm:grid-cols-2';
      case 3:
        return 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3';
      case 4:
        return 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4';
    }
  });
</script>

<div class={cn(colClass, gap === 'sm' ? 'gap-2' : 'gap-4', className)}>
  {@render children()}
</div>
