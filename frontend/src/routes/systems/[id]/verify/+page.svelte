<script lang="ts">
	import { page } from '$app/state';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Alert from '$lib/components/ui/alert';
	import { Label } from '$lib/components/ui/label';
	import CodeEditor, { type LineStatus } from '$lib/components/code-editor.svelte';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import BackLink from '$lib/components/BackLink.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import ProofResults, { lineTone } from '$lib/components/ProofResults.svelte';
	import { api, ApiError, type VerifyResponse } from '$lib/api';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';

	// The system is fixed; only its name is needed here — proofs are checked
	// server-side against the stored rows, not against any client-held source.
	let systemName = $state<string | null>(null);
	let loadingSystem = $state(true);
	let loadError = $state<string | null>(null);

	let proofText = $state('');
	let verifying = $state(false);
	let result = $state<VerifyResponse | null>(null);
	let requestError = $state<string | null>(null);

	// Drop late responses from a previous system id (see PR3's detail page).
	let loadSeq = 0;
	let verifySeq = 0;
	let editor = $state<{ focusLine: (index: number) => void } | undefined>(undefined);

	const lineStatuses = $derived.by<LineStatus[]>(() => {
		const parsed = result?.proof;
		const lines = proofText.split('\n');
		if (!parsed || parsed.lines.length !== lines.length) return [];
		return parsed.lines.map(lineTone);
	});

	async function loadSystem(id: string) {
		const seq = ++loadSeq;
		// Invalidate any in-flight verify so its result can't land in the new
		// system's workbench (the two sequences are otherwise independent).
		verifySeq++;
		verifying = false;
		loadingSystem = true;
		loadError = null;
		result = null;
		requestError = null;
		try {
			const detail = await api.systems.get(id);
			if (seq !== loadSeq) return;
			systemName = detail.name;
		} catch (err) {
			if (seq !== loadSeq) return;
			loadError =
				err instanceof ApiError
					? err.status === 404
						? 'This system does not exist, or is a private draft.'
						: err.message
					: String(err);
			systemName = null;
		} finally {
			if (seq === loadSeq) loadingSystem = false;
		}
	}

	async function verify(id: string, text: string) {
		const seq = ++verifySeq;
		verifying = true;
		requestError = null;
		try {
			const res = await api.systems.verify(id, text);
			if (seq !== verifySeq) return;
			result = res;
		} catch (err) {
			if (seq !== verifySeq) return;
			if (err instanceof ApiError) {
				// A 400 means the stored system no longer compiles; the backend
				// returns the compile errors as detail, already formatted.
				requestError = err.status === 400 ? `System did not compile:\n${err.message}` : err.message;
			} else {
				requestError = String(err);
			}
			result = null;
		} finally {
			if (seq === verifySeq) verifying = false;
		}
	}

	$effect(() => {
		const id = page.params.id;
		if (id) loadSystem(id);
	});

	// Debounced live verify: re-checks a beat after typing stops, so results track
	// the editor without a button. Empty input clears back to the idle hint.
	// Bumping verifySeq on every edit invalidates any in-flight response so a slow
	// reply can't repopulate diagnostics for newer (or cleared) text.
	$effect(() => {
		const text = proofText;
		const id = page.params.id;
		if (!id || systemName === null) return;
		verifySeq++;
		verifying = false;
		if (!text.trim()) {
			result = null;
			requestError = null;
			return;
		}
		const timer = setTimeout(() => verify(id, text), 450);
		return () => clearTimeout(timer);
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
	{:else if loadingSystem || systemName === null}
		<LoadingSpinner message="Loading system…" />
	{:else}
		<PageHeader
			title="Verify a proof"
			description={systemName ? `Checked against ${systemName}, line by line.` : undefined}
		/>

		<div class="grid items-start gap-6 lg:grid-cols-2">
			<Card.Root>
				<Card.Header>
					<div class="flex items-center justify-between gap-2">
						<Card.Title>Proof</Card.Title>
						<div class="flex items-center gap-2">
							{#if verifying}
								<span class="inline-flex items-center gap-1 text-xs text-muted-foreground">
									<LoaderCircle class="size-3 animate-spin" /> Checking…
								</span>
							{/if}
							<Button variant="ghost" size="sm" onclick={() => (proofText = '')}>
								<RotateCcw class="size-3.5" /> Clear
							</Button>
						</div>
					</div>
					<Card.Description>
						One statement per line, in {systemName ?? 'this system'} — checked live as you type.
					</Card.Description>
				</Card.Header>
				<Card.Content class="flex flex-col gap-2">
					<Label for="proof-text" class="sr-only">Proof text</Label>
					<CodeEditor
						id="proof-text"
						bind:value={proofText}
						bind:this={editor}
						rows={14}
						showLineNumbers
						{lineStatuses}
					/>
				</Card.Content>
			</Card.Root>

			<ProofResults
				{result}
				{requestError}
				idleMessage="Start typing a proof to see line-by-line results here."
				onLineClick={(i) => editor?.focusLine(i)}
			/>
		</div>
	{/if}
</PageContainer>
