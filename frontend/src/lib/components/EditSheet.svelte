<script lang="ts">
  import * as Sheet from '$lib/components/ui/sheet';
  import { Button } from '$lib/components/ui/button';
  import SymbolPalette from '$lib/components/SymbolPalette.svelte';
  import type { SymbolEntry } from '$lib/symbols';
  import { cn } from '$lib/utils';
  import type { Snippet } from 'svelte';

  type Props = {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    title: string;
    description?: string;
    contentClass?: string;
    children: Snippet;
    onSave: () => void;
    onDelete?: () => void;
    saving?: boolean;
    /** When false, Save is disabled and submitting is a no-op (invalid form). */
    canSave?: boolean;
    /** Set (even to `[]`) to show a symbol palette above the form, typing into
     *  whichever `data-symbol-field` input was last focused. */
    symbols?: SymbolEntry[];
  };

  let {
    open,
    onOpenChange,
    title,
    description,
    contentClass,
    children,
    onSave,
    onDelete,
    saving = false,
    canSave = true,
    symbols
  }: Props = $props();

  let form = $state<HTMLFormElement | null>(null);
</script>

<Sheet.Root {open} {onOpenChange}>
  <Sheet.Content side="right" class={cn('w-full sm:max-w-lg', contentClass)}>
    <Sheet.Header>
      <Sheet.Title>{title}</Sheet.Title>
      {#if description}
        <Sheet.Description>{description}</Sheet.Description>
      {/if}
    </Sheet.Header>
    {#if symbols}
      <!-- Outside the scrolling form so it stays put while the fields scroll. -->
      <div class="border-b px-6 pb-3">
        <SymbolPalette root={form} {symbols} />
      </div>
    {/if}
    <form
      bind:this={form}
      onsubmit={(e) => {
        e.preventDefault();
        if (canSave && !saving) onSave();
      }}
      class="flex flex-1 flex-col gap-4 overflow-y-auto px-6 py-4"
    >
      {@render children()}
    </form>
    <Sheet.Footer class="flex-row justify-between border-t px-6 py-4">
      {#if onDelete}
        <Button variant="destructive" size="sm" type="button" onclick={onDelete} disabled={saving}>
          Delete
        </Button>
      {:else}
        <div></div>
      {/if}
      <Button size="sm" onclick={onSave} disabled={saving || !canSave}>
        {saving ? 'Saving...' : 'Save Changes'}
      </Button>
    </Sheet.Footer>
  </Sheet.Content>
</Sheet.Root>
