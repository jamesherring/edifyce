<script lang="ts">
  import { cn } from '$lib/utils';
  import type { Snippet } from 'svelte';

  type Props = {
    level?: 'section' | 'subsection' | 'label';
    class?: string;
    children: Snippet;
  };

  let { level = 'section', class: className, children }: Props = $props();

  const classes = $derived.by(() => {
    switch (level) {
      case 'section':
        return 'mb-3 text-sm font-medium';
      case 'subsection':
        return 'mb-2 text-xs font-medium text-muted-foreground uppercase';
      case 'label':
        return 'mb-1 text-xs text-muted-foreground uppercase';
    }
  });
</script>

<div class={cn(classes, className)}>
  {@render children()}
</div>
