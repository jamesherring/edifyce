<script lang="ts">
	import { tick } from 'svelte';
	import { Textarea } from '$lib/components/ui/textarea';
	import { cn } from '$lib/utils';

	let {
		value = $bindable(''),
		placeholder,
		rows = 14,
		class: className,
		id
	}: {
		value?: string;
		placeholder?: string;
		rows?: number;
		class?: string;
		id?: string;
	} = $props();

	// Insert spaces instead of moving focus when Tab is pressed inside the editor.
	// Shift+Tab is left alone so keyboard users can still move focus backward.
	async function handleKeydown(event: KeyboardEvent) {
		if (event.key !== 'Tab' || event.shiftKey) return;
		event.preventDefault();

		const el = event.currentTarget as HTMLTextAreaElement;
		const start = el.selectionStart;
		const end = el.selectionEnd;
		const indent = '    ';

		value = value.slice(0, start) + indent + value.slice(end);

		// Wait for Svelte to flush the bound value to the DOM before restoring
		// the caret, otherwise the selection is clobbered by the re-render.
		await tick();
		el.selectionStart = el.selectionEnd = start + indent.length;
	}
</script>

<Textarea
	{id}
	bind:value
	{placeholder}
	{rows}
	spellcheck="false"
	autocapitalize="off"
	onkeydown={handleKeydown}
	class={cn('bg-muted/30 resize-y font-mono leading-relaxed', className)}
/>
