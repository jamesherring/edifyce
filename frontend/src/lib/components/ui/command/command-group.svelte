<script lang="ts">
  import { Command as CommandPrimitive } from 'bits-ui';
  import { cn, type WithoutChildrenOrChild } from '$lib/utils.js';

  let {
    ref = $bindable(null),
    class: className,
    ...restProps
  }: WithoutChildrenOrChild<CommandPrimitive.GroupProps> & {
    children: import('svelte').Snippet;
  } = $props();
</script>

<CommandPrimitive.Group
  bind:ref
  data-slot="command-group"
  class={cn('overflow-hidden p-1 text-foreground', className)}
  {...restProps}
/>
