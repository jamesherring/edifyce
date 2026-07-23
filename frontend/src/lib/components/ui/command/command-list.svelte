<script lang="ts">
  import { Command as CommandPrimitive } from 'bits-ui';
  import { cn, type WithoutChildrenOrChild } from '$lib/utils.js';

  let {
    ref = $bindable(null),
    class: className,
    ...restProps
  }: WithoutChildrenOrChild<CommandPrimitive.ListProps> & {
    children: import('svelte').Snippet;
  } = $props();
</script>

<CommandPrimitive.List
  bind:ref
  data-slot="command-list"
  class={cn('max-h-[300px] scroll-py-1 overflow-x-hidden overflow-y-auto', className)}
  {...restProps}
/>
