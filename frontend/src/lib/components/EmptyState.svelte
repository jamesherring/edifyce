<script lang="ts">
  import ActionButton from '$lib/components/ActionButton.svelte';
  import type { Snippet } from 'svelte';

  type Props = {
    title: string;
    description: string;
    actionLabel?: string;
    onAction?: () => void;
    secondaryActionLabel?: string;
    onSecondaryAction?: () => void;
    icon?: Snippet;
  };

  let {
    title,
    description,
    actionLabel,
    onAction,
    secondaryActionLabel,
    onSecondaryAction,
    icon
  }: Props = $props();
</script>

<div class="flex flex-col items-center justify-center py-16 text-center">
  <div
    class="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-primary/20 bg-primary/5"
  >
    {#if icon}
      {@render icon()}
    {:else}
      <svg
        class="h-7 w-7 text-primary/40"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
      >
        <path d="M12 5v14M5 12h14" />
      </svg>
    {/if}
  </div>
  <h3 class="mb-2 text-lg font-medium text-foreground">{title}</h3>
  <p class="mb-6 max-w-sm text-sm text-muted-foreground">{description}</p>
  {#if (actionLabel && onAction) || (secondaryActionLabel && onSecondaryAction)}
    <div class="flex flex-wrap items-center justify-center gap-2">
      {#if actionLabel && onAction}
        <ActionButton onclick={onAction}>{actionLabel}</ActionButton>
      {/if}
      {#if secondaryActionLabel && onSecondaryAction}
        <ActionButton variant="outline" onclick={onSecondaryAction}>
          {secondaryActionLabel}
        </ActionButton>
      {/if}
    </div>
  {/if}
</div>
