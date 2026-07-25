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
		/** Whether the full catalogue is showing. Bindable so a host with limited
		 *  room (an edit sheet) can keep only one authoring aid open at a time. */
		expanded?: boolean;
		class?: string;
	};

	let {
		root = null,
		symbols = [],
		expanded = $bindable(false),
		class: className
	}: Props = $props();

	// A system with no notation of its own yet still needs somewhere to start.
	const STARTER = SYMBOL_GROUPS[0].symbols.slice(0, 8);
	const quick = $derived(symbols.length > 0 ? symbols : STARTER);

	let active = $state<TextField | null>(null);
	let quickStrip = $state<HTMLDivElement | null>(null);
	let catalogueStrip = $state<HTMLDivElement | null>(null);
	let quickIndex = $state(0);
	let catalogueIndex = $state(0);
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

	/** The field an insert lands in: the one last focused, or — before the user has
	 *  focused anything — the first target in the container, so an early click
	 *  isn't silently dropped. */
	function target(): TextField | null {
		if (active) {
			// The field being typed into has since left the DOM (a repeatable row was
			// removed). Drop the insert rather than quietly writing the symbol into
			// some other field the user never touched.
			if (!active.isConnected) active = null;
			return active;
		}
		return root?.querySelector<TextField>(SYMBOL_FIELD_SELECTOR) ?? null;
	}

	function insert(char: string) {
		const el = target();
		if (!el) return;
		active = el;
		insertAtCaret(el, char);
	}

	// Roving tabindex: each strip of keys is a single tab stop whose arrow keys
	// move between symbols, rather than making a keyboard user tab past every
	// button to reach the editor below.
	function rove(
		event: KeyboardEvent,
		container: HTMLElement | null,
		setIndex: (index: number) => void
	) {
		const buttons = [...(container?.querySelectorAll<HTMLButtonElement>('button') ?? [])];
		if (buttons.length === 0) return;
		const from = Math.max(0, buttons.indexOf(document.activeElement as HTMLButtonElement));
		let next: number;
		switch (event.key) {
			case 'ArrowRight':
			case 'ArrowDown':
				next = (from + 1) % buttons.length;
				break;
			case 'ArrowLeft':
			case 'ArrowUp':
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
		setIndex(next);
		buttons[next].focus();
	}

	/** Which key in a strip carries the tab stop, clamped so a shrinking strip
	 *  (the catalogue as a search narrows it) always keeps exactly one. */
	function stop(index: number, count: number): number {
		return Math.min(index, Math.max(0, count - 1));
	}

	const filtered = $derived.by(() => {
		const q = query.trim().toLowerCase();
		if (!q) return SYMBOL_GROUPS;
		return SYMBOL_GROUPS.map((group) => ({
			title: group.title,
			symbols: group.symbols.filter((s) => s.name.includes(q) || s.char === query.trim())
		})).filter((group) => group.symbols.length > 0);
	});

	// The catalogue's groups form one continuous strip for the roving tabindex, so
	// each group needs to know how many keys precede it.
	const groupOffsets = $derived.by(() => {
		const offsets: number[] = [];
		let seen = 0;
		for (const group of filtered) {
			offsets.push(seen);
			seen += group.symbols.length;
		}
		return offsets;
	});
	const catalogueCount = $derived(filtered.reduce((n, group) => n + group.symbols.length, 0));
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
			bind:this={quickStrip}
			role="toolbar"
			tabindex="-1"
			aria-label="Insert a symbol"
			class="flex flex-wrap items-center gap-1.5"
			onkeydown={(e) => rove(e, quickStrip, (i) => (quickIndex = i))}
		>
			{#each quick as symbol, i (symbol.char)}
				{@render key(symbol, i === stop(quickIndex, quick.length) ? 0 : -1)}
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
			     sheet's fields) off screen; the search stays put above it. Its groups
			     are one roving strip, so reaching the editor below is a single Tab
			     rather than a hundred-odd. -->
			<div
				bind:this={catalogueStrip}
				role="toolbar"
				tabindex="-1"
				aria-label="Symbol catalogue"
				class="flex max-h-40 flex-col gap-3 overflow-y-auto sm:max-h-56"
				onkeydown={(e) => rove(e, catalogueStrip, (i) => (catalogueIndex = i))}
			>
				{#if filtered.length === 0}
					<p class="text-muted-foreground py-2 text-center text-xs">
						No symbol matches “{query.trim()}”.
					</p>
				{:else}
					{#each filtered as group, groupIndex (group.title)}
						<div class="flex flex-col gap-1.5">
							<p class="text-muted-foreground text-xs font-medium">{group.title}</p>
							<div class="flex flex-wrap gap-1.5">
								{#each group.symbols as symbol, i (symbol.char)}
									{@render key(
										symbol,
										groupOffsets[groupIndex] + i === stop(catalogueIndex, catalogueCount) ? 0 : -1
									)}
								{/each}
							</div>
						</div>
					{/each}
				{/if}
			</div>
		</div>
	{/if}
</div>
