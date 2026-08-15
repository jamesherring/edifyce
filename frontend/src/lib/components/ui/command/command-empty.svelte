<script lang="ts">
  import { Command as CommandPrimitive } from 'bits-ui';
  import { cn, type WithoutChildrenOrChild } from '$lib/utils.js';

  let {
    ref = $bindable(null),
    class: className,
    ...restProps
  }: WithoutChildrenOrChild<CommandPrimitive.EmptyProps> & {
    children: import('svelte').Snippet;
  } = $props();
</script>

<CommandPrimitive.Empty
  bind:ref
  data-slot="command-empty"
  class={cn('py-6 text-center text-sm text-muted-foreground', className)}
  {...restProps}
/>
