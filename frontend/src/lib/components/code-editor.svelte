<script lang="ts">
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
	function handleKeydown(event: KeyboardEvent) {
		if (event.key !== 'Tab') return;
		event.preventDefault();

		const el = event.currentTarget as HTMLTextAreaElement;
		const start = el.selectionStart;
		const end = el.selectionEnd;
		const indent = '    ';

		value = value.slice(0, start) + indent + value.slice(end);
		requestAnimationFrame(() => {
			el.selectionStart = el.selectionEnd = start + indent.length;
		});
	}
</script>

<textarea
	{id}
	bind:value
	{placeholder}
	{rows}
	spellcheck="false"
	autocapitalize="off"
	onkeydown={handleKeydown}
	class={cn(
		'border-input placeholder:text-muted-foreground focus-visible:ring-ring bg-muted/30 w-full resize-y rounded-md border px-3 py-2 font-mono text-sm leading-relaxed shadow-sm focus-visible:outline-none focus-visible:ring-1 disabled:cursor-not-allowed disabled:opacity-50',
		className
	)}
></textarea>
