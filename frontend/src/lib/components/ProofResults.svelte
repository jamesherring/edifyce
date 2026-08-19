<script lang="ts" module>
	import CircleCheck from '@lucide/svelte/icons/circle-check-big';
	import CircleX from '@lucide/svelte/icons/circle-x';
	import CircleAlert from '@lucide/svelte/icons/circle-alert';
	import CircleDashed from '@lucide/svelte/icons/circle-dashed';
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

	/** What a line's marker says, beyond the tone its row is tinted with.
	 *
	 * An open goal is not a mistake — `failure.code === 'hole'` is work left, and
	 * a cross over it reads as a wrong step — so it gets a mark of its own. */
	export type Marker = Tone | 'hole';

	export const MARKER: Record<Marker, { icon: Component; class: string }> = {
		ok: { icon: CircleCheck, class: 'text-success' },
		warning: { icon: CircleAlert, class: 'text-warning' },
		error: { icon: CircleX, class: 'text-destructive' },
		hole: { icon: CircleDashed, class: 'text-muted-foreground' }
	};

	/**
	 * The marker a line gets, or null when there is nothing worth marking.
	 *
	 * A tick on every line of a valid proof is noise: the card's own badge
	 * already says the proof checked, and repeating it forty times says nothing
	 * per line. So `verdicts` is for the editor, where a tick appearing as you
	 * type *is* the feedback; a reader gets a mark only where something is off.
	 */
	export function lineMarker(line: ProofLine, verdicts: boolean): Marker | null {
		if (!line.valid) return line.failure?.code === 'hole' ? 'hole' : 'error';
		if (line.warning_message) return 'warning';
		return verdicts ? 'ok' : null;
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
	import JustificationCard from '$lib/components/JustificationCard.svelte';
	import { isTeX } from '$lib/math';
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
		/** The notation the lines on screen were read through — the *served*
		 *  reading, not the one being fetched. It decides whether a re-spelled line
		 *  is TeX to typeset, and it is what a citation's card is read in, so one
		 *  row is never half in one spelling and half in another. */
		notation?: string | null;
		title?: string;
		description?: string;
		/** Top-right of the header — the browse view's notation picker. */
		actions?: Snippet;
		/** Under the description — the browse view's reading status and errors. */
		controls?: Snippet;
		/** The card-level verdict badge. On for the editor, where a check is the
		 *  thing being run and its verdict is the answer. Off for a reader, whose
		 *  page already carries the proof's status beside its title, and where a
		 *  second copy over the lines only asks to be read as a fresh result. */
		indicator?: boolean;
		/** Mark every line, valid ones included. For the editor, where a tick
		 *  appearing as you type is the feedback; a reader is shown only what is
		 *  off. */
		verdicts?: boolean;
		/** The system's primary line type, whose name every ordinary line carries
		 *  and so says nothing. Lines of any *other* type keep their badge, which
		 *  is where the type is the interesting thing (`assume`, `fresh`, a
		 *  comment). Unset suppresses nothing — a caller that has not said which
		 *  type is the default has not claimed any of them is. */
		primaryLineType?: string | null;
		/** The proof these lines belong to. It resolves a label local to it — a
		 *  hypothesis of the theorem it establishes — and, with `explain`, buys the
		 *  *substitution* half of a citation's card. */
		proofId?: string | null;
		/** Whether this reader may pay for that substitution: deriving it means
		 *  asking the server to re-check the step, which is signed-in only. Without
		 *  it the card still opens, on what the label alone says. */
		explain?: boolean;
		/** The system the citations resolve in. What the rows-only half of a card
		 *  is looked up in, so a signed-out reader gets one at all. Unset leaves
		 *  citations as plain text. */
		systemId?: string | null;
	};

	let {
		result,
		requestError = null,
		idleMessage = 'Verify the proof to see line-by-line results here.',
		onLineClick,
		lines = null,
		notation = null,
		title = 'Verification',
		description = undefined,
		actions,
		controls,
		indicator = true,
		verdicts = true,
		primaryLineType = null,
		proofId = null,
		explain = false,
		systemId = null
	}: Props = $props();

	// The payload's lines are the fallback, not the default: a caller passing
	// `lines` has already decided what the rows are (and where they came from).
	const rows = $derived(lines ?? (result?.proof ? resultLines(result.proof.lines) : null));
	const tex = $derived(isTeX(notation));
</script>

<Card.Root>
	<Card.Header>
		<div class="flex items-center justify-between gap-2">
			<Card.Title>{title}</Card.Title>
			<div class="flex shrink-0 items-center gap-2">
				{#if indicator && result?.proof}
					{@const meta = TONE[indicatorTone(result.proof.indicator)]}
					{@const Icon = meta.icon}
					<Badge variant={meta.badge}><Icon /> {meta.text}</Badge>
				{/if}
				{#if actions}{@render actions()}{/if}
			</div>
		</div>
		{#if description}<Card.Description>{description}</Card.Description>{/if}
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
					{@const meta = TONE[lineTone(line)]}
					{@const marker = lineMarker(line, verdicts)}
					{@const Icon = marker === null ? null : MARKER[marker].icon}
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
								<!-- The formula reads left, its justification right: a proof is a
								     column of statements, and putting the citation under each one
								     doubles the height of every row to say what a reader scans
								     for in a second column. -->
								<div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
									<div
										class={[
											'min-w-0 flex-1 text-sm break-words',
											!(tex && line.typeset) && 'font-mono'
										]}
										style={`padding-left: ${line.indent * 1.25}rem`}
									>
										{#if tex && line.typeset && line.display}
											<Typeset tex={line.display} />
										{:else}
											{line.display || ' '}
										{/if}
									</div>

									<div
										class="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground"
									>
										{#if line.name && line.name !== primaryLineType}
											<!-- Only where the type is the interesting thing. Every
											     ordinary line carries the system's primary type, so
											     badging it labels the whole proof `statement`. -->
											<Badge variant="outline">{line.name}</Badge>
										{/if}
										{#if line.label}
											<span>{line.label}</span>
										{/if}
										{#if line.reference}
											<JustificationCard
												{proofId}
												{explain}
												{systemId}
												label={line.rule}
												number={line.number ?? null}
												citation={line.reference}
												{notation}
											/>
										{/if}
										{#if Icon}
											<Icon class={['size-3.5 shrink-0', MARKER[marker!].class]} />
										{/if}
									</div>
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
