<script lang="ts" module>
	/** Per-line diagnostic tone, aligned index-for-index with the editor's lines. */
	export type LineStatus = 'ok' | 'warning' | 'error' | null;
</script>

<script lang="ts">
	import { tick } from 'svelte';
	import { Textarea } from '$lib/components/ui/textarea';
	import { cn } from '$lib/utils';

	let {
		value = $bindable(''),
		placeholder,
		rows = 14,
		class: className,
		id,
		showLineNumbers = false,
		lineStatuses = []
	}: {
		value?: string;
		placeholder?: string;
		rows?: number;
		class?: string;
		id?: string;
		/** Render a line-number gutter (tinted by `lineStatuses`) beside the text. */
		showLineNumbers?: boolean;
		lineStatuses?: LineStatus[];
	} = $props();

	let textarea = $state<HTMLTextAreaElement | null>(null);
	let gutter = $state<HTMLDivElement | null>(null);

	const lineCount = $derived(Math.max(1, value.split('\n').length));

	// The gutter is a separate scroll box; mirror the textarea's scroll so the
	// numbers stay aligned with their lines.
	function syncScroll() {
		if (gutter && textarea) gutter.scrollTop = textarea.scrollTop;
	}

	/** Focus the editor and select line `index` (0-based), scrolling it into view.
	 *  Lets a caller (e.g. a verification result) jump to the offending line. */
	export function focusLine(index: number): void {
		const el = textarea;
		if (!el) return;
		const lines = value.split('\n');
		const line = Math.max(0, Math.min(index, lines.length - 1));
		let start = 0;
		for (let i = 0; i < line; i++) start += lines[i].length + 1;
		const end = start + lines[line].length;
		el.focus();
		el.setSelectionRange(start, end);
		const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 20;
		el.scrollTop = Math.max(0, line * lineHeight - el.clientHeight / 2);
		syncScroll();
	}

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

{#if showLineNumbers}
	<div
		class={cn(
			'border-input bg-muted/30 focus-within:ring-ring flex overflow-hidden rounded-md border text-sm shadow-sm focus-within:ring-1',
			className
		)}
	>
		<div
			bind:this={gutter}
			aria-hidden="true"
			class="text-muted-foreground/70 shrink-0 overflow-hidden py-2 pr-2 pl-3 text-right font-mono leading-relaxed tabular-nums select-none"
		>
			{#each Array(lineCount) as _, i (i)}
				<div
					class={[
						'leading-relaxed',
						lineStatuses[i] === 'error' && 'text-destructive font-medium',
						lineStatuses[i] === 'warning' && 'text-warning font-medium',
						lineStatuses[i] === 'ok' && 'text-success'
					]}
				>
					{i + 1}
				</div>
			{/each}
		</div>
		<!-- wrap="off": each logical line is exactly one visual row, so the gutter
		     numbers and per-line tints stay aligned (long lines scroll sideways). -->
		<textarea
			bind:this={textarea}
			{id}
			bind:value
			{placeholder}
			{rows}
			wrap="off"
			data-symbol-field
			spellcheck="false"
			autocapitalize="off"
			onkeydown={handleKeydown}
			onscroll={syncScroll}
			class="flex-1 resize-y overflow-auto bg-transparent py-2 pr-3 pl-2 font-mono text-sm leading-relaxed outline-none"
		></textarea>
	</div>
{:else}
	<Textarea
		{id}
		bind:value
		{placeholder}
		{rows}
		data-symbol-field
		spellcheck="false"
		autocapitalize="off"
		onkeydown={handleKeydown}
		class={cn('bg-muted/30 resize-y font-mono leading-relaxed', className)}
	/>
{/if}
