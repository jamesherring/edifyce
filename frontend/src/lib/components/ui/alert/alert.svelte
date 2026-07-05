<script lang="ts" module>
	import { type VariantProps, tv } from 'tailwind-variants';

	export const alertVariants = tv({
		base: 'relative w-full rounded-lg border px-4 py-3 text-sm grid grid-cols-[0_1fr] has-[>svg]:grid-cols-[calc(var(--spacing)*4)_1fr] gap-y-0.5 items-start [&>svg]:size-4 [&>svg]:translate-y-0.5 [&>svg]:text-current gap-x-3',
		variants: {
			variant: {
				default: 'bg-card text-card-foreground',
				destructive:
					'text-destructive bg-card [&>svg]:text-current *:data-[slot=alert-description]:text-destructive/90 border-destructive/50',
				success:
					'text-success bg-card [&>svg]:text-current border-success/40',
				warning: 'text-warning bg-card [&>svg]:text-current border-warning/40'
			}
		},
		defaultVariants: {
			variant: 'default'
		}
	});

	export type AlertVariant = VariantProps<typeof alertVariants>['variant'];
</script>

<script lang="ts">
	import type { HTMLAttributes } from 'svelte/elements';
	import type { Snippet } from 'svelte';
	import { cn } from '$lib/utils';

	let {
		class: className,
		variant = 'default',
		children,
		...restProps
	}: HTMLAttributes<HTMLDivElement> & { variant?: AlertVariant; children?: Snippet } = $props();
</script>

<div class={cn(alertVariants({ variant }), className)} role="alert" {...restProps}>
	{@render children?.()}
</div>
