<script lang="ts">
  import { Button, type ButtonProps } from '$lib/components/ui/button';
  import { cn } from '$lib/utils.js';

  let { class: className, children, ...restProps }: ButtonProps = $props();
</script>

<Button class={cn('shadow-lg shadow-primary/20', className)} {...restProps}>
  {@render children?.()}
</Button>
