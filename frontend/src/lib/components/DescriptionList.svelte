<script lang="ts">
  import { cn } from '$lib/utils';

  type Item = {
    label: string;
    value: string;
    mono?: boolean;
  };

  type Props = {
    items: Item[];
    columns?: 1 | 2;
    class?: string;
  };

  let { items, columns = 2, class: className }: Props = $props();
</script>

<dl
  class={cn(
    'grid grid-cols-1 gap-y-3 text-sm',
    columns === 2 && 'sm:grid-cols-2 sm:gap-x-6',
    className
  )}
>
  {#each items as item (item.label)}
    <div>
      <dt class="text-muted-foreground">{item.label}</dt>
      <dd class={cn(item.mono && 'truncate font-mono text-xs')}>{item.value}</dd>
    </div>
  {/each}
</dl>
