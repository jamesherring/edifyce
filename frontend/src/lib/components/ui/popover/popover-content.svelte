<script lang="ts">
  import { Popover as PopoverPrimitive } from 'bits-ui';
  import { cn, type WithoutChildrenOrChild } from '$lib/utils.js';

  let {
    ref = $bindable(null),
    class: className,
    align = 'center',
    sideOffset = 4,
    portalProps,
    children,
    ...restProps
  }: WithoutChildrenOrChild<PopoverPrimitive.ContentProps> & {
    portalProps?: PopoverPrimitive.PortalProps;
    children: import('svelte').Snippet;
  } = $props();
</script>

<PopoverPrimitive.Portal {...portalProps}>
  <PopoverPrimitive.Content
    bind:ref
    data-slot="popover-content"
    {align}
    {sideOffset}
    class={cn(
      'z-50 w-72 rounded-md border bg-popover p-4 text-popover-foreground shadow-md outline-hidden data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95',
      className
    )}
    {...restProps}
  >
    {@render children?.()}
  </PopoverPrimitive.Content>
</PopoverPrimitive.Portal>
