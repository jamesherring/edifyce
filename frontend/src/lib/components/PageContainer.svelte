<script lang="ts">
  import { cn } from '$lib/utils';
  import type { Snippet } from 'svelte';

  type MaxWidth = 'sm' | 'md' | 'lg' | 'xl' | '2xl' | '3xl' | '4xl' | '5xl' | 'full';
  type Padding = 'default' | 'comfortable';

  type Props = {
    maxWidth?: MaxWidth;
    padding?: Padding;
    gap?: boolean;
    class?: string;
    children: Snippet;
  };

  let {
    maxWidth = 'full',
    padding = 'default',
    gap = false,
    class: className,
    children
  }: Props = $props();

  const maxWidthClasses: Record<MaxWidth, string> = {
    sm: 'mx-auto max-w-sm',
    md: 'mx-auto max-w-md',
    lg: 'mx-auto max-w-lg',
    xl: 'mx-auto max-w-xl',
    '2xl': 'mx-auto max-w-2xl',
    '3xl': 'mx-auto max-w-3xl',
    '4xl': 'mx-auto max-w-4xl',
    '5xl': 'mx-auto max-w-5xl',
    full: ''
  };

  const paddingClasses: Record<Padding, string> = {
    default: 'p-4 sm:p-6',
    comfortable: 'px-4 py-6 sm:px-6 sm:py-10'
  };
</script>

<div class={cn(maxWidthClasses[maxWidth], paddingClasses[padding], gap && 'space-y-6', className)}>
  {@render children()}
</div>
