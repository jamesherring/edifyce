<script lang="ts">
	import * as Alert from '$lib/components/ui/alert';
	import type { SystemValidation } from '$lib/api';
	import CircleCheck from '@lucide/svelte/icons/circle-check-big';
	import CircleX from '@lucide/svelte/icons/circle-x';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';

	type Props = {
		validation: SystemValidation | null;
		validating: boolean;
		/** Sidebar rendering: same information, sized to sit beside the outline. */
		compact?: boolean;
	};

	let { validation, validating, compact = false }: Props = $props();
</script>

{#if compact}
	<div class="flex flex-col gap-2 text-xs">
		{#if validating && !validation}
			<span class="text-muted-foreground inline-flex items-center gap-1.5">
				<LoaderCircle class="size-3.5 animate-spin" /> Checking…
			</span>
		{:else if validation?.success}
			<span class="text-success inline-flex items-center gap-1.5 font-medium">
				<CircleCheck class="size-3.5 shrink-0" /> Compiles cleanly
			</span>
			<span class="text-muted-foreground">
				{validation.line_type_count ?? 0} line type(s), {validation.inference_rule_count ?? 0} rule(s).
			</span>
		{:else if validation}
			<span class="text-destructive inline-flex items-center gap-1.5 font-medium">
				<CircleX class="size-3.5 shrink-0" /> Does not compile ({validation.errors.length})
			</span>
			<!-- Capped: a badly broken system can report dozens of errors, and the
			     outline below it has to stay reachable. -->
			<ul class="flex max-h-48 flex-col gap-1 overflow-y-auto">
				{#each validation.errors as err (err)}
					<li class="border-destructive/30 bg-destructive/5 rounded border px-1.5 py-1 font-mono">
						{err}
					</li>
				{/each}
			</ul>
		{/if}
	</div>
{:else if validating && !validation}
	<div class="bg-muted/30 text-muted-foreground rounded-md border p-3 text-sm">Checking…</div>
{:else if validation?.success}
	<Alert.Root variant="success">
		<CircleCheck class="size-4" />
		<Alert.Title>Compiles cleanly</Alert.Title>
		<Alert.Description>
			{validation.line_type_count ?? 0} line type(s), {validation.inference_rule_count ?? 0} inference
			rule(s).
		</Alert.Description>
	</Alert.Root>
{:else if validation}
	<Alert.Root variant="destructive">
		<CircleX class="size-4" />
		<Alert.Title>Does not compile ({validation.errors.length})</Alert.Title>
		<Alert.Description>
			<ul class="mt-1 space-y-1">
				{#each validation.errors as err (err)}
					<li
						class="border-destructive/30 bg-destructive/5 rounded border px-2 py-1 font-mono text-xs"
					>
						{err}
					</li>
				{/each}
			</ul>
		</Alert.Description>
	</Alert.Root>
{/if}
