<script lang="ts">
  import * as Sheet from '$lib/components/ui/sheet';
  import { Button } from '$lib/components/ui/button';
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
    canSave = true
  }: Props = $props();
</script>

<Sheet.Root {open} {onOpenChange}>
  <Sheet.Content side="right" class={cn('w-full sm:max-w-lg', contentClass)}>
    <Sheet.Header>
      <Sheet.Title>{title}</Sheet.Title>
      {#if description}
        <Sheet.Description>{description}</Sheet.Description>
      {/if}
    </Sheet.Header>
    <form
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
