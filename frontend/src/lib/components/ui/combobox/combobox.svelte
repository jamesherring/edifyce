<script lang="ts" module>
  export interface ComboboxOption {
    /** The stable value returned on selection (e.g. a proof id). */
    value: string;
    /** The primary line shown in the list and, when selected, on the trigger. */
    label: string;
    /** Optional muted secondary text shown beside the label (e.g. "draft"). */
    hint?: string;
    /** Extra text folded into the search match beyond the label. */
    keywords?: string;
    disabled?: boolean;
  }
</script>

<script lang="ts">
  import * as Popover from '$lib/components/ui/popover/index.js';
  import * as Command from '$lib/components/ui/command/index.js';
  import { buttonVariants } from '$lib/components/ui/button/index.js';
  import CheckIcon from '@lucide/svelte/icons/check';
  import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
  import { cn } from '$lib/utils.js';
  import { tick } from 'svelte';

  let {
    options,
    value = $bindable(null),
    onSelect,
    placeholder = 'Select…',
    searchPlaceholder = 'Search…',
    emptyText = 'No matches.',
    disabled = false,
    ariaLabel,
    class: className
  }: {
    options: ComboboxOption[];
    /** Bindable selected value, or null when nothing is chosen. */
    value?: string | null;
    /** Called with the chosen value; the picker closes and resets its search. */
    onSelect?: (value: string) => void;
    placeholder?: string;
    searchPlaceholder?: string;
    emptyText?: string;
    disabled?: boolean;
    /** Accessible name for the trigger. The placeholder alone leaves it unnamed
     *  once a value is chosen, and says nothing about what is being picked. */
    ariaLabel?: string;
    class?: string;
  } = $props();

  let open = $state(false);
  let search = $state('');
  let triggerRef = $state<HTMLButtonElement | null>(null);

  const selected = $derived(options.find((o) => o.value === value) ?? null);

  // Refocus the trigger after closing so keyboard flow returns where it started —
  // the shadcn-svelte combobox convention (bits-ui warns if focus is left adrift).
  function closeAndFocus() {
    open = false;
    search = '';
    tick().then(() => triggerRef?.focus());
  }

  function pick(v: string) {
    value = v;
    onSelect?.(v);
    closeAndFocus();
  }
</script>

<Popover.Root bind:open>
  <Popover.Trigger
    bind:ref={triggerRef}
    {disabled}
    class={cn(
      buttonVariants({ variant: 'outline' }),
      'w-full justify-between font-normal',
      !selected && 'text-muted-foreground',
      className
    )}
    role="combobox"
    aria-label={ariaLabel}
    aria-expanded={open}
  >
    <span class="truncate">{selected ? selected.label : placeholder}</span>
    <ChevronDownIcon class="opacity-50" />
  </Popover.Trigger>
  <Popover.Content class="w-[var(--bits-floating-anchor-width)] p-0" align="start">
    <Command.Root>
      <Command.Input
        placeholder={searchPlaceholder}
        aria-label={searchPlaceholder}
        bind:value={search}
      />
      <Command.List>
        <Command.Empty>{emptyText}</Command.Empty>
        <Command.Group>
          {#each options as option (option.value)}
            <Command.Item
              value={`${option.label} ${option.keywords ?? ''}`}
              disabled={option.disabled}
              onSelect={() => pick(option.value)}
            >
              <CheckIcon
                class={cn('size-4', option.value === value ? 'opacity-100' : 'opacity-0')}
              />
              <span class="truncate">{option.label}</span>
              {#if option.hint}
                <span class="ms-auto text-xs text-muted-foreground">{option.hint}</span>
              {/if}
            </Command.Item>
          {/each}
        </Command.Group>
      </Command.List>
    </Command.Root>
  </Popover.Content>
</Popover.Root>
