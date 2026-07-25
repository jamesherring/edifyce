<script lang="ts">
	import { SYMBOL_GROUPS, type SymbolEntry } from '$lib/symbols';
	import {
		SYMBOL_FIELD_SELECTOR,
		insertAtCaret,
		isTextField,
		type TextField
	} from '$lib/symbol-insert';
	import { Input } from '$lib/components/ui/input';
	import { cn } from '$lib/utils';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';

	type Props = {
		/** Container whose `data-symbol-field` inputs this palette types into. */
		root?: HTMLElement | null;
		/** Symbols to lead with — normally the ones the system's own notation uses. */
		symbols?: SymbolEntry[];
		class?: string;
	};

	let { root = null, symbols = [], class: className }: Props = $props();

	// A system with no notation of its own yet still needs somewhere to start.
	const STARTER = SYMBOL_GROUPS[0].symbols.slice(0, 8);
	const quick = $derived(symbols.length > 0 ? symbols : STARTER);

	let active = $state<TextField | null>(null);
	let toolbar = $state<HTMLDivElement | null>(null);
	let focusIndex = $state(0);
	let expanded = $state(false);
	let query = $state('');

	// Track the last-focused target rather than the currently-focused one: clicking
	// a palette button (or opening the picker) moves focus off the field, and the
	// insert still has to land where the user was typing.
	$effect(() => {
		const container = root;
		if (!container) return;
		const onFocusIn = (event: FocusEvent) => {
			if (isTextField(event.target) && event.target.matches(SYMBOL_FIELD_SELECTOR)) {
				active = event.target;
			}
		};
		container.addEventListener('focusin', onFocusIn);
		return () => {
			container.removeEventListener('focusin', onFocusIn);
			active = null;
		};
	});

	/** The field an insert lands in: the last-focused one, or — before the user has
	 *  focused anything, or once a removed row's input has left the DOM — the first
	 *  target in the container, so a click is never silently dropped. */
	function target(): TextField | null {
		if (active?.isConnected) return active;
		return root?.querySelector<TextField>(SYMBOL_FIELD_SELECTOR) ?? null;
	}

	function insert(char: string) {
		const el = target();
		if (!el) return;
		active = el;
		insertAtCaret(el, char);
	}

	// Roving tabindex: the whole strip is one tab stop and the arrow keys move
	// between symbols, rather than making a keyboard user tab past every button.
	function onToolbarKeydown(event: KeyboardEvent) {
		const buttons = [...(toolbar?.querySelectorAll<HTMLButtonElement>('button') ?? [])];
		if (buttons.length === 0) return;
		const from = Math.max(0, buttons.indexOf(document.activeElement as HTMLButtonElement));
		let next: number;
		switch (event.key) {
			case 'ArrowRight':
				next = (from + 1) % buttons.length;
				break;
			case 'ArrowLeft':
				next = (from - 1 + buttons.length) % buttons.length;
				break;
			case 'Home':
				next = 0;
				break;
			case 'End':
				next = buttons.length - 1;
				break;
			default:
				return;
		}
		event.preventDefault();
		focusIndex = next;
		buttons[next].focus();
	}

	const filtered = $derived.by(() => {
		const q = query.trim().toLowerCase();
		if (!q) return SYMBOL_GROUPS;
		return SYMBOL_GROUPS.map((group) => ({
			title: group.title,
			symbols: group.symbols.filter((s) => s.name.includes(q) || s.char === query.trim())
		})).filter((group) => group.symbols.length > 0);
	});
</script>

{#snippet key(symbol: SymbolEntry, tabindex: number)}
	<button
		type="button"
		{tabindex}
		title={`${symbol.char}  ${symbol.name}`}
		aria-label={`Insert ${symbol.name}`}
		class="border-input hover:bg-accent hover:text-accent-foreground focus-visible:ring-ring inline-flex size-8 shrink-0 items-center justify-center rounded-md border font-mono text-sm transition-colors focus-visible:ring-2 focus-visible:outline-none"
		onmousedown={(e) => e.preventDefault()}
		onclick={() => insert(symbol.char)}
	>
		{symbol.char}
	</button>
{/snippet}

<div class={cn('flex flex-col gap-2', className)}>
	<div class="flex flex-wrap items-center gap-1.5">
		<!-- `onmousedown` is prevented on every key so the target field keeps its
		     selection: the insert replaces what was selected, as typing would. -->
		<div
			bind:this={toolbar}
			role="toolbar"
			tabindex="-1"
			aria-label="Insert a symbol"
			class="flex flex-wrap items-center gap-1.5"
			onkeydown={onToolbarKeydown}
		>
			{#each quick as symbol, i (symbol.char)}
				{@render key(symbol, i === Math.min(focusIndex, quick.length - 1) ? 0 : -1)}
			{/each}
		</div>
		<button
			type="button"
			class="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs focus-visible:ring-2 focus-visible:outline-none"
			aria-expanded={expanded}
			onclick={() => (expanded = !expanded)}
		>
			<ChevronDown class={cn('size-3.5 transition-transform', expanded && 'rotate-180')} />
			{expanded ? 'Fewer symbols' : 'More symbols'}
		</button>
	</div>

	{#if expanded}
		<div class="bg-muted/30 flex flex-col gap-3 rounded-md border p-3">
			<Input
				bind:value={query}
				placeholder="Search symbols… (e.g. “subset”)"
				aria-label="Search symbols"
				class="h-8"
			/>
			<!-- Capped and scrolled so the full catalogue can't shove the editor (or a
			     sheet's fields) off screen; the search stays put above it. -->
			<div class="flex max-h-56 flex-col gap-3 overflow-y-auto">
				{#if filtered.length === 0}
					<p class="text-muted-foreground py-2 text-center text-xs">
						No symbol matches “{query.trim()}”.
					</p>
				{:else}
					{#each filtered as group (group.title)}
						<div class="flex flex-col gap-1.5">
							<p class="text-muted-foreground text-xs font-medium">{group.title}</p>
							<div class="flex flex-wrap gap-1.5">
								{#each group.symbols as symbol (symbol.char)}
									{@render key(symbol, 0)}
								{/each}
							</div>
						</div>
					{/each}
				{/if}
			</div>
		</div>
	{/if}
</div>
