<script lang="ts">
  import { cn } from '$lib/utils';

  type Props = {
    message: string;
    size?: 'sm' | 'default';
    centered?: boolean;
    class?: string;
  };

  let { message, size = 'default', centered = false, class: className }: Props = $props();
</script>

<p
  class={cn(
    'text-muted-foreground',
    size === 'sm' ? 'text-xs' : 'text-sm',
    centered && 'py-4 text-center',
    className
  )}
>
  {message}
</p>
