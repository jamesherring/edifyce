<script lang="ts">
  import * as Sheet from '$lib/components/ui/sheet';
  import { Button } from '$lib/components/ui/button';
  import SymbolPalette from '$lib/components/SymbolPalette.svelte';
  import NotationReference from '$lib/components/NotationReference.svelte';
  import type { SymbolEntry } from '$lib/symbols';
  import type { NotationGroup } from '$lib/notation';
  import { cn } from '$lib/utils';
  import { tick, type Snippet } from 'svelte';

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
    /** The grammar this form is written against, shown as a collapsible reference
     *  beside the palette. */
    notation?: NotationGroup[];
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
    symbols,
    notation = []
  }: Props = $props();

  let form = $state<HTMLFormElement | null>(null);

  // Whether anything renders above the form. Both authoring aids are optional and
  // independent, so the block shows for either — and the focus override below has
  // to key off the same condition, not just `symbols`.
  const hasAids = $derived(!!symbols || notation.length > 0);

  // A sheet is a fixed-height column: header, aids, scrolling form, footer. Two
  // expanded aids starve the form of every pixel — on a phone that left the
  // fields unreachable — so only one is open at a time.
  let paletteOpen = $state(false);
  let referenceOpen = $state(false);
  $effect(() => {
    if (paletteOpen) referenceOpen = false;
  });
  $effect(() => {
    if (referenceOpen) paletteOpen = false;
  });

  // The sheet otherwise focuses its first tabbable node on open, which an aid
  // would be — leaving the user typing into nothing (and Space inserting a
  // symbol). Put the caret in the first field instead, which is where it landed
  // before the aids existed.
  async function focusFirstField(event: Event) {
    event.preventDefault();
    await tick();
    form?.querySelector<HTMLElement>('input, textarea, select')?.focus();
  }
</script>

<Sheet.Root {open} {onOpenChange}>
  <Sheet.Content
    side="right"
    class={cn('w-full sm:max-w-lg', contentClass)}
    onOpenAutoFocus={hasAids ? focusFirstField : undefined}
  >
    <Sheet.Header>
      <Sheet.Title>{title}</Sheet.Title>
      {#if description}
        <Sheet.Description>{description}</Sheet.Description>
      {/if}
    </Sheet.Header>
    {#if hasAids}
      <!-- Outside the scrolling form so it stays put while the fields scroll. -->
      <div class="flex flex-col gap-2 border-b px-6 pb-3">
        {#if symbols}
          <SymbolPalette root={form} {symbols} bind:expanded={paletteOpen} />
        {/if}
        <NotationReference groups={notation} bind:open={referenceOpen} />
      </div>
    {/if}
    <form
      bind:this={form}
      onsubmit={(e) => {
        e.preventDefault();
        if (canSave && !saving) onSave();
      }}
      class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 py-4"
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
        {saving ? 'Saving…' : 'Save changes'}
      </Button>
    </Sheet.Footer>
  </Sheet.Content>
</Sheet.Root>
