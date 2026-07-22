<script lang="ts">
	import { Badge } from '$lib/components/ui/badge';

	type Props = {
		/** The cached verification verdict: null = never checked. */
		valid: boolean | null;
	};

	let { valid }: Props = $props();

	const meta = $derived(
		valid === null
			? { variant: 'outline' as const, text: 'Unchecked' }
			: valid
				? { variant: 'success' as const, text: 'Valid' }
				: { variant: 'destructive' as const, text: 'Invalid' }
	);
</script>

<Badge variant={meta.variant}>{meta.text}</Badge>
