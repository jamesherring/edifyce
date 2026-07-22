<script lang="ts">
	import { page } from '$app/state';
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Alert from '$lib/components/ui/alert';
	import { Label } from '$lib/components/ui/label';
	import CodeEditor from '$lib/components/code-editor.svelte';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import BackLink from '$lib/components/BackLink.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import ProofResults from '$lib/components/ProofResults.svelte';
	import { api, ApiError, type VerifyResponse } from '$lib/api';
	import Play from '@lucide/svelte/icons/play';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import Code from '@lucide/svelte/icons/code';

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
		// Invalidate any in-flight verify so its result can't land in the new
		// system's workbench (the two sequences are otherwise independent).
		verifySeq++;
		verifying = false;
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

			<ProofResults {result} {requestError} idleMessage="Verify a proof to see line-by-line results here." />
		</div>
	{/if}
</PageContainer>
