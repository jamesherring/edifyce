<script lang="ts">
  import { cn } from '$lib/utils';
  import type { Snippet } from 'svelte';

  type Props = {
    title: string;
    subtitle?: string;
    icon?: Snippet;
    badges?: Snippet;
    actions?: Snippet;
    class?: string;
  };

  let { title, subtitle, icon, badges, actions, class: className }: Props = $props();
</script>

<div class={cn('flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between', className)}>
  <div class="flex min-w-0 items-center gap-4">
    {#if icon}
      <div class="shrink-0">
        {@render icon()}
      </div>
    {/if}
    <div class="min-w-0">
      <h1 class="truncate text-xl font-semibold tracking-tight">{title}</h1>
      {#if subtitle}
        <p class="text-sm text-muted-foreground">{subtitle}</p>
      {/if}
      {#if badges}
        <div class="mt-2 flex flex-wrap items-center gap-2">
          {@render badges()}
        </div>
      {/if}
    </div>
  </div>
  {#if actions}
    <div class="shrink-0">
      {@render actions()}
    </div>
  {/if}
</div>
