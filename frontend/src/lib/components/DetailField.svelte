<script lang="ts">
  import { cn } from '$lib/utils';
  import type { Snippet } from 'svelte';

  type Props = {
    label: string;
    value?: string;
    mono?: boolean;
    class?: string;
    children?: Snippet;
  };

  let { label, value, mono = true, class: className, children }: Props = $props();
</script>

<div class={cn(className)}>
  <div class="mb-1 text-xs text-muted-foreground uppercase">{label}</div>
  {#if children}
    {@render children()}
  {:else}
    <div class={cn('text-sm', mono && 'font-mono')}>{value ?? '-'}</div>
  {/if}
</div>
