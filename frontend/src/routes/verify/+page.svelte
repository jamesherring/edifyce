<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Alert from '$lib/components/ui/alert';
	import { Badge } from '$lib/components/ui/badge';
	import { Label } from '$lib/components/ui/label';
	import CodeEditor from '$lib/components/code-editor.svelte';
	import { api, ApiError, type VerifyResponse, type ProofLine } from '$lib/api';
	import { EXAMPLE_SYSTEM, EXAMPLE_PROOF } from '$lib/examples';
	import type { Component } from 'svelte';
	import Play from '@lucide/svelte/icons/play';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import CircleCheck from '@lucide/svelte/icons/circle-check-big';
	import CircleX from '@lucide/svelte/icons/circle-x';
	import CircleAlert from '@lucide/svelte/icons/circle-alert';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';

	type Tone = 'ok' | 'warning' | 'error';

	// Single source of truth for how each diagnostic level is presented, used by
	// both the overall badge and the per-line markers.
	const TONE: Record<
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

	let systemCode = $state(EXAMPLE_SYSTEM);
	let proofText = $state(EXAMPLE_PROOF);
	let loading = $state(false);
	let result = $state<VerifyResponse | null>(null);
	let requestError = $state<string | null>(null);

	async function verify() {
		loading = true;
		result = null;
		requestError = null;
		try {
			result = await api.verify(systemCode, proofText);
		} catch (err) {
			if (err instanceof ApiError) {
				// A 400 means the system failed to compile; the backend returns the
				// compile errors as detail, already formatted into err.message.
				requestError =
					err.status === 400 ? `System did not compile:\n${err.message}` : err.message;
			} else {
				requestError = String(err);
			}
		} finally {
			loading = false;
		}
	}

	function reset() {
		systemCode = EXAMPLE_SYSTEM;
		proofText = EXAMPLE_PROOF;
		result = null;
		requestError = null;
	}

	function lineTone(line: ProofLine): Tone {
		if (!line.valid) return 'error';
		if (line.warning_message) return 'warning';
		return 'ok';
	}

	// The overall proof indicator ("ok"/"warning"/"error") maps onto the same
	// tone vocabulary; fall back to "error" for any unexpected value.
	function indicatorTone(indicator: string): Tone {
		return indicator === 'ok' || indicator === 'warning' ? indicator : 'error';
	}
</script>

<div class="flex flex-col gap-2">
	<h1 class="text-2xl font-bold tracking-tight">Verify a proof</h1>
	<p class="text-muted-foreground">
		Compile a formal system and check a proof against it, line by line. Sends
		<code class="text-foreground">POST /proofs/verify</code>.
	</p>
</div>

<div class="mt-6 grid gap-6 lg:grid-cols-2">
	<div class="flex flex-col gap-6">
		<Card.Root>
			<Card.Header>
				<div class="flex items-center justify-between">
					<Card.Title>Formal system</Card.Title>
					<Button variant="ghost" size="sm" onclick={reset}>
						<RotateCcw class="size-3.5" /> Reset
					</Button>
				</div>
				<Card.Description>The system your proof is written against.</Card.Description>
			</Card.Header>
			<Card.Content class="flex flex-col gap-2">
				<Label for="system-code">System code</Label>
				<CodeEditor id="system-code" bind:value={systemCode} rows={12} />
			</Card.Content>
		</Card.Root>

		<Card.Root>
			<Card.Header>
				<Card.Title>Proof</Card.Title>
				<Card.Description>One statement per line.</Card.Description>
			</Card.Header>
			<Card.Content class="flex flex-col gap-4">
				<div class="flex flex-col gap-2">
					<Label for="proof-text">Proof text</Label>
					<CodeEditor id="proof-text" bind:value={proofText} rows={6} />
				</div>
				<Button onclick={verify} disabled={loading || systemCode.trim().length === 0}>
					{#if loading}
						<LoaderCircle class="size-4 animate-spin" /> Verifying…
					{:else}
						<Play class="size-4" /> Verify proof
					{/if}
				</Button>
			</Card.Content>
		</Card.Root>
	</div>

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
				<p class="text-muted-foreground py-8 text-center text-sm">
					Verify a proof to see line-by-line results here.
				</p>
			{:else if !result.proof}
				<!-- The system compiled but the checker raised (structured error);
				     `proof` is null only on that path. -->
				<Alert.Root variant="destructive">
					<TriangleAlert />
					<Alert.Title>Proof could not be checked</Alert.Title>
					<Alert.Description>
						{#each result.errors as error, i (i)}
							<span class="font-mono">{error}</span>
						{/each}
					</Alert.Description>
				</Alert.Root>
			{:else}
				<ol class="flex flex-col gap-2">
					{#each result.proof.lines as line, i (i)}
						{@const tone = lineTone(line)}
						{@const meta = TONE[tone]}
						{@const Icon = meta.icon}
						<li class={['rounded-md border px-3 py-2', meta.row]}>
							<div class="flex items-start gap-3">
								<span class="text-muted-foreground w-5 pt-0.5 text-right text-xs tabular-nums">
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
											<span class="text-muted-foreground text-xs">by {line.reference}</span>
										{/if}
										{#if line.label}
											<span class="text-muted-foreground text-xs">· {line.label}</span>
										{/if}
									</div>

									{#if line.invalid_message}
										<p class="text-destructive mt-1 text-xs">{line.invalid_message}</p>
									{/if}
									{#if line.warning_message}
										<p class="text-warning mt-1 text-xs">{line.warning_message}</p>
									{/if}
								</div>
							</div>
						</li>
					{/each}
				</ol>

				{#if result.proof.lines.length === 0}
					<p class="text-muted-foreground py-6 text-center text-sm">
						The proof is empty — add some lines above.
					</p>
				{/if}
			{/if}
		</Card.Content>
	</Card.Root>
</div>
