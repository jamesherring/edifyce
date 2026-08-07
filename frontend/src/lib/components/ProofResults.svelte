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
	import Typeset from '$lib/components/Typeset.svelte';
	import type { VerifyResponse } from '$lib/api';
	import { resultLines, type ReadLine } from '$lib/reading';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import type { Snippet } from 'svelte';

	type Props = {
		result: VerifyResponse | null;
		requestError?: string | null;
		/** Shown before the first verify, in place of the "verify to see results" hint. */
		idleMessage?: string;
		/** When set, each line row becomes a button that reports its 0-based index —
		 *  lets the caller jump the editor to the matching line. */
		onLineClick?: (index: number) => void;
		/** The rows to show, when they are not the ones `result` carries — a proof
		 *  read through a notation comes off the *stored structure* instead, which
		 *  is where a re-spelled term lives. Falls back to the payload's own. */
		lines?: ReadLine[] | null;
		/** Whether a re-spelled line is TeX to typeset rather than text to show. */
		tex?: boolean;
		title?: string;
		description?: string;
		/** Beside the verdict badge — the browse view's Verify button. */
		actions?: Snippet;
		/** Under the description — the browse view's notation switch. */
		controls?: Snippet;
	};

	let {
		result,
		requestError = null,
		idleMessage = 'Verify the proof to see line-by-line results here.',
		onLineClick,
		lines = null,
		tex = false,
		title = 'Verification',
		description = 'Each proof line and its diagnostics.',
		actions,
		controls
	}: Props = $props();

	// The payload's lines are the fallback, not the default: a caller passing
	// `lines` has already decided what the rows are (and where they came from).
	const rows = $derived(lines ?? (result?.proof ? resultLines(result.proof.lines) : null));
</script>

<Card.Root>
	<Card.Header>
		<div class="flex items-center justify-between gap-2">
			<Card.Title>{title}</Card.Title>
			<div class="flex shrink-0 items-center gap-2">
				{#if result?.proof}
					{@const meta = TONE[indicatorTone(result.proof.indicator)]}
					{@const Icon = meta.icon}
					<Badge variant={meta.badge}><Icon /> {meta.text}</Badge>
				{/if}
				{#if actions}{@render actions()}{/if}
			</div>
		</div>
		<Card.Description>{description}</Card.Description>
		{#if controls}{@render controls()}{/if}
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
		{:else if result !== null && !result.proof}
			<!-- The system compiled but the checker raised (structured error);
			     `proof` is null only on that path. Ahead of the rows, since the last
			     check produced none and any it replaced are stale. -->
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
		{:else if rows === null}
			<p class="py-8 text-center text-sm text-muted-foreground">{idleMessage}</p>
		{:else if rows.length === 0}
			<p class="py-6 text-center text-sm text-muted-foreground">
				The proof is empty — add some lines.
			</p>
		{:else}
			<!-- A checked proof can still carry errors that explain the check rather
			     than replace it: a cited lemma that has not been verified leaves its
			     citation unresolved, and without this the line just looks wrong. -->
			{#if result && result.errors.length > 0}
				<Alert.Root variant="destructive">
					<TriangleAlert />
					<Alert.Title>A cited proof could not be used</Alert.Title>
					<Alert.Description>
						<div class="mt-1 space-y-1">
							{#each result.errors as error, i (i)}
								<p class="text-xs">{error}</p>
							{/each}
						</div>
					</Alert.Description>
				</Alert.Root>
			{/if}
			<ol class="flex flex-col gap-2">
				{#each rows as line, i (i)}
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
							<!-- The citation number, not the text position: blank lines and
							     commentary carry none, so the gutter agrees with what a
							     reference like `[MP, 1, 2]` actually names. A payload cached
							     before numbering existed omits the field entirely, and was
							     numbered by position — render those as they were. -->
							<span class="w-5 pt-0.5 text-right text-xs text-muted-foreground tabular-nums">
								{line.number === undefined ? i + 1 : (line.number ?? '')}
							</span>
							<div class="min-w-0 flex-1">
								<div
									class={['text-sm break-words', !(tex && line.typeset) && 'font-mono']}
									style={`padding-left: ${line.indent * 1.25}rem`}
								>
									{#if tex && line.typeset && line.display}
										<Typeset tex={line.display} />
									{:else}
										{line.display || ' '}
									{/if}
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
