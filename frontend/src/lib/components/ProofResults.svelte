<script lang="ts" module>
	import CircleCheck from '@lucide/svelte/icons/circle-check-big';
	import CircleX from '@lucide/svelte/icons/circle-x';
	import CircleAlert from '@lucide/svelte/icons/circle-alert';
	import type { Component } from 'svelte';
	import type { ProofLine } from '$lib/api';

	export type Tone = 'ok' | 'warning' | 'error';

	// Single source of truth for how each diagnostic level is presented, shared by
	// the overall badge and the per-line markers.
	export const TONE: Record<
		Tone,
		{ icon: Component; badge: 'success' | 'warning' | 'destructive'; text: string; row: string }
	> = {
		ok: { icon: CircleCheck, badge: 'success', text: 'Valid', row: 'bg-muted/30' },
		warning: {
			icon: CircleAlert,
			badge: 'warning',
			text: 'Warnings',
			row: 'border-warning/40 bg-warning/5'
		},
		error: {
			icon: CircleX,
			badge: 'destructive',
			text: 'Invalid',
			row: 'border-destructive/40 bg-destructive/5'
		}
	};

	export function lineTone(line: ProofLine): Tone {
		if (!line.valid) return 'error';
		if (line.warning_message) return 'warning';
		return 'ok';
	}

	// The overall proof indicator ("ok"/"warning"/"error") maps onto the same tone
	// vocabulary; fall back to "error" for any unexpected value.
	export function indicatorTone(indicator: string): Tone {
		return indicator === 'ok' || indicator === 'warning' ? indicator : 'error';
	}
</script>

<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import * as Alert from '$lib/components/ui/alert';
	import { Badge } from '$lib/components/ui/badge';
	import type { VerifyResponse } from '$lib/api';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';

	type Props = {
		result: VerifyResponse | null;
		requestError?: string | null;
		/** Shown before the first verify, in place of the "verify to see results" hint. */
		idleMessage?: string;
		/** When set, each line row becomes a button that reports its 0-based index —
		 *  lets the caller jump the editor to the matching line. */
		onLineClick?: (index: number) => void;
	};

	let {
		result,
		requestError = null,
		idleMessage = 'Verify the proof to see line-by-line results here.',
		onLineClick
	}: Props = $props();
</script>

<Card.Root>
	<Card.Header>
		<div class="flex items-center justify-between gap-2">
			<Card.Title>Verification</Card.Title>
			{#if result?.proof}
				{@const meta = TONE[indicatorTone(result.proof.indicator)]}
				{@const Icon = meta.icon}
				<Badge variant={meta.badge}><Icon /> {meta.text}</Badge>
			{/if}
		</div>
		<Card.Description>Each proof line and its diagnostics.</Card.Description>
	</Card.Header>
	<Card.Content class="flex flex-col gap-4">
		{#if requestError}
			<Alert.Root variant="destructive">
				<TriangleAlert />
				<Alert.Title>Could not verify</Alert.Title>
				<Alert.Description>
					<span class="whitespace-pre-wrap">{requestError}</span>
				</Alert.Description>
			</Alert.Root>
		{:else if result === null}
			<p class="py-8 text-center text-sm text-muted-foreground">{idleMessage}</p>
		{:else if !result.proof}
			<!-- The system compiled but the checker raised (structured error);
			     `proof` is null only on that path. -->
			<Alert.Root variant="destructive">
				<TriangleAlert />
				<Alert.Title>Proof could not be checked</Alert.Title>
				<Alert.Description>
					<div class="mt-1 space-y-1">
						{#each result.errors as error, i (i)}
							<p class="font-mono text-xs">{error}</p>
						{/each}
					</div>
				</Alert.Description>
			</Alert.Root>
		{:else if result.proof.lines.length === 0}
			<p class="py-6 text-center text-sm text-muted-foreground">
				The proof is empty — add some lines.
			</p>
		{:else}
			<ol class="flex flex-col gap-2">
				{#each result.proof.lines as line, i (i)}
					{@const tone = lineTone(line)}
					{@const meta = TONE[tone]}
					{@const Icon = meta.icon}
					<li class={['rounded-md border px-3 py-2', meta.row]}>
						<svelte:element
							this={onLineClick ? 'button' : 'div'}
							type={onLineClick ? 'button' : undefined}
							role={onLineClick ? 'button' : undefined}
							class={[
								'flex w-full items-start gap-3',
								onLineClick &&
									'focus-visible:ring-ring -mx-1 cursor-pointer rounded px-1 text-left hover:bg-black/[0.03] focus-visible:ring-2 focus-visible:outline-none dark:hover:bg-white/[0.04]'
							]}
							aria-label={onLineClick ? `Go to line ${i + 1} in the editor` : undefined}
							onclick={onLineClick ? () => onLineClick(i) : undefined}
						>
							<span class="w-5 pt-0.5 text-right text-xs text-muted-foreground tabular-nums">
								{i + 1}
							</span>
							<div class="min-w-0 flex-1">
								<div
									class="font-mono text-sm break-words"
									style={`padding-left: ${line.indent * 1.25}rem`}
								>
									{line.display || ' '}
								</div>

								<div class="mt-1.5 flex flex-wrap items-center gap-1.5">
									<Icon
										class={[
											'size-3.5',
											tone === 'ok' && 'text-success',
											tone === 'warning' && 'text-warning',
											tone === 'error' && 'text-destructive'
										]}
									/>
									{#if line.name}
										<Badge variant="outline">{line.name}</Badge>
									{/if}
									{#if line.reference}
										<span class="text-xs text-muted-foreground">by {line.reference}</span>
									{/if}
									{#if line.label}
										<span class="text-xs text-muted-foreground">· {line.label}</span>
									{/if}
								</div>

								{#if line.invalid_message}
									<p class="mt-1 text-xs text-destructive">{line.invalid_message}</p>
								{/if}
								{#if line.warning_message}
									<p class="mt-1 text-xs text-warning">{line.warning_message}</p>
								{/if}
							</div>
						</svelte:element>
					</li>
				{/each}
			</ol>
		{/if}
	</Card.Content>
</Card.Root>
