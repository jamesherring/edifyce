<script lang="ts">
	import { page } from '$app/state';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Alert from '$lib/components/ui/alert';
	import { Badge } from '$lib/components/ui/badge';
	import { Label } from '$lib/components/ui/label';
	import CodeEditor from '$lib/components/code-editor.svelte';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import BackLink from '$lib/components/BackLink.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import { api, ApiError, type VerifyResponse, type ProofLine } from '$lib/api';
	import type { Component } from 'svelte';
	import Play from '@lucide/svelte/icons/play';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import CircleCheck from '@lucide/svelte/icons/circle-check-big';
	import CircleX from '@lucide/svelte/icons/circle-x';
	import CircleAlert from '@lucide/svelte/icons/circle-alert';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import Code from '@lucide/svelte/icons/code';

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

	// The system is fixed; its source is fetched from the store, not editable here.
	let systemName = $state<string | null>(null);
	let systemCode = $state<string | null>(null);
	let loadingSystem = $state(true);
	let loadError = $state<string | null>(null);
	let sourceOpen = $state(false);

	let proofText = $state('');
	let verifying = $state(false);
	let result = $state<VerifyResponse | null>(null);
	let requestError = $state<string | null>(null);

	// Drop late responses from a previous system id (see PR3's detail page).
	let loadSeq = 0;
	let verifySeq = 0;

	async function loadSystem(id: string) {
		const seq = ++loadSeq;
		loadingSystem = true;
		loadError = null;
		result = null;
		requestError = null;
		try {
			const [detail, src] = await Promise.all([api.systems.get(id), api.systems.source(id)]);
			if (seq !== loadSeq) return;
			systemName = detail.name;
			systemCode = src.source;
		} catch (err) {
			if (seq !== loadSeq) return;
			loadError =
				err instanceof ApiError
					? err.status === 404
						? 'This system does not exist, or is a private draft.'
						: err.message
					: String(err);
			systemName = null;
			systemCode = null;
		} finally {
			if (seq === loadSeq) loadingSystem = false;
		}
	}

	async function verify() {
		if (!systemCode) return;
		const seq = ++verifySeq;
		verifying = true;
		result = null;
		requestError = null;
		try {
			const res = await api.verify(systemCode, proofText);
			if (seq !== verifySeq) return;
			result = res;
		} catch (err) {
			if (seq !== verifySeq) return;
			if (err instanceof ApiError) {
				// A 400 means the stored system no longer compiles; the backend
				// returns the compile errors as detail, already formatted.
				requestError =
					err.status === 400 ? `System did not compile:\n${err.message}` : err.message;
			} else {
				requestError = String(err);
			}
		} finally {
			if (seq === verifySeq) verifying = false;
		}
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

	$effect(() => {
		const id = page.params.id;
		if (id) loadSystem(id);
	});
</script>

<PageContainer maxWidth="5xl" gap>
	<BackLink href={`/systems/${page.params.id}`} label="Back to system" />

	{#if loadError}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>System unavailable</Alert.Title>
			<Alert.Description>{loadError}</Alert.Description>
		</Alert.Root>
	{:else if loadingSystem || systemCode === null}
		<LoadingSpinner message="Loading system…" />
	{:else}
		<PageHeader
			title="Verify a proof"
			description={systemName ? `Checked against ${systemName}, line by line.` : undefined}
		/>

		<div class="grid gap-6 lg:grid-cols-2">
			<div class="flex flex-col gap-6">
				<Card.Root>
					<Card.Header>
						<div class="flex items-center justify-between gap-2">
							<Card.Title>Proof</Card.Title>
							<Button variant="ghost" size="sm" onclick={() => (proofText = '')}>
								<RotateCcw class="size-3.5" /> Clear
							</Button>
						</div>
						<Card.Description>One statement per line, in {systemName ?? 'this system'}.</Card.Description>
					</Card.Header>
					<Card.Content class="flex flex-col gap-4">
						<div class="flex flex-col gap-2">
							<Label for="proof-text">Proof text</Label>
							<CodeEditor id="proof-text" bind:value={proofText} rows={10} />
						</div>
						<Button onclick={verify} disabled={verifying}>
							{#if verifying}
								<LoaderCircle class="size-4 animate-spin" /> Verifying…
							{:else}
								<Play class="size-4" /> Verify proof
							{/if}
						</Button>
					</Card.Content>
				</Card.Root>

				<!-- The system's notation/rules for reference while writing the proof. -->
				<Card.Root>
					<Card.Header>
						<Button variant="ghost" size="sm" class="-ml-2 w-fit" onclick={() => (sourceOpen = !sourceOpen)}>
							<Code class="size-3.5" />
							{sourceOpen ? 'Hide system source' : 'Show system source'}
						</Button>
					</Card.Header>
					{#if sourceOpen}
						<Card.Content>
							<pre class="overflow-x-auto rounded-md border bg-muted/30 p-4 font-mono text-xs leading-relaxed">{systemCode}</pre>
						</Card.Content>
					{/if}
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
						<p class="py-8 text-center text-sm text-muted-foreground">
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
									<div class="flex items-start gap-3">
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
									</div>
								</li>
							{/each}
						</ol>
					{/if}
				</Card.Content>
			</Card.Root>
		</div>
	{/if}
</PageContainer>
