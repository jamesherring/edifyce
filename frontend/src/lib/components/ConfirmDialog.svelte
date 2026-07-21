<script lang="ts">
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';

	type Props = {
		open: boolean;
		title: string;
		description?: string;
		confirmLabel?: string;
		variant?: 'default' | 'destructive';
		loading?: boolean;
		onConfirm: () => void;
		onCancel: () => void;
	};

	let {
		open = $bindable(false),
		title,
		description,
		confirmLabel = 'Confirm',
		variant = 'default',
		loading = false,
		onConfirm,
		onCancel
	}: Props = $props();

	// Dismissing via overlay/escape counts as a cancel, but not while the action
	// is in flight.
	function handleOpenChange(next: boolean) {
		if (!next && !loading) onCancel();
	}
</script>

<Dialog.Root bind:open onOpenChange={handleOpenChange}>
	<Dialog.Content>
		<Dialog.Header>
			<Dialog.Title>{title}</Dialog.Title>
			{#if description}
				<Dialog.Description>{description}</Dialog.Description>
			{/if}
		</Dialog.Header>
		<Dialog.Footer>
			<Button variant="outline" onclick={onCancel} disabled={loading}>Cancel</Button>
			<Button {variant} onclick={onConfirm} disabled={loading}>
				{#if loading}
					<LoaderCircle class="size-4 animate-spin" />
				{/if}
				{confirmLabel}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
