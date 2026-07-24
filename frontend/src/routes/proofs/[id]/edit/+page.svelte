<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Textarea } from '$lib/components/ui/textarea';
	import CodeEditor, { type LineStatus } from '$lib/components/code-editor.svelte';
	import * as Card from '$lib/components/ui/card';
	import * as Alert from '$lib/components/ui/alert';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import BackLink from '$lib/components/BackLink.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import CheckBadge from '$lib/components/CheckBadge.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import ProofResults, { lineTone } from '$lib/components/ProofResults.svelte';
	import LemmasPanel from '$lib/components/LemmasPanel.svelte';
	import { api, ApiError, type ProofDetail, type VerifyResponse } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { toastSuccess, toastError } from '$lib/toast';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import Save from '@lucide/svelte/icons/save';
	import Trash2 from '@lucide/svelte/icons/trash-2';

	let proof = $state<ProofDetail | null>(null);
	let loading = $state(true);
	let loadError = $state<string | null>(null);

	let name = $state('');
	let description = $state('');
	let source = $state('');
	let savingSource = $state(false);
	let savingDetails = $state(false);
	let publishing = $state(false);

	// Live verification of the *current editor text* against the proof's system —
	// no save needed. (This checks syntax + rule application; saved lemma citations
	// only resolve on save, see the note below, so authoritative validity is the
	// verdict recorded by `saveSource`.)
	let liveResult = $state<VerifyResponse | null>(null);
	let liveVerifying = $state(false);
	let liveError = $state<string | null>(null);
	let liveSeq = 0;

	let confirmOpen = $state(false);
	let deleting = $state(false);

	let loadSeq = 0;
	let editor = $state<{ focusLine: (index: number) => void } | undefined>(undefined);

	const isOwner = $derived(!!auth.user && !!proof && proof.owner?.id === auth.user.id);
	const dirty = $derived(!!proof && source !== proof.source);
	const detailsDirty = $derived(
		!!proof && (name.trim() !== proof.name || (description.trim() || null) !== (proof.description ?? null))
	);

	// Tint the gutter only when the live result lines line up one-for-one with the
	// editor's lines; otherwise (e.g. blank lines the parser drops) leave it plain
	// rather than colour the wrong rows. The right-hand pane stays authoritative.
	const lineStatuses = $derived.by<LineStatus[]>(() => {
		const parsed = liveResult?.proof;
		const editorLines = source.split('\n');
		if (!parsed || parsed.lines.length !== editorLines.length) return [];
		return parsed.lines.map(lineTone);
	});

	async function load(id: string) {
		const seq = ++loadSeq;
		loading = true;
		loadError = null;
		try {
			const detail = await api.proofs.get(id);
			if (seq !== loadSeq) return;
			proof = detail;
			name = detail.name;
			description = detail.description ?? '';
			source = detail.source;
			liveResult = null;
			liveError = null;
		} catch (err) {
			if (seq !== loadSeq) return;
			loadError =
				err instanceof ApiError
					? err.status === 404
						? 'This proof does not exist, or is a private draft.'
						: err.message
					: String(err);
			proof = null;
		} finally {
			if (seq === loadSeq) loading = false;
		}
	}

	async function runLiveVerify(systemId: string, text: string) {
		const seq = ++liveSeq;
		liveVerifying = true;
		liveError = null;
		try {
			const res = await api.systems.verify(systemId, text);
			if (seq !== liveSeq) return;
			liveResult = res;
		} catch (err) {
			if (seq !== liveSeq) return;
			liveError =
				err instanceof ApiError
					? err.status === 400
						? `System did not compile:\n${err.message}`
						: err.message
					: String(err);
			liveResult = null;
		} finally {
			if (seq === liveSeq) liveVerifying = false;
		}
	}

	// Debounced live verify: re-checks a short beat after typing stops. Bumping
	// liveSeq on *every* edit invalidates any still-in-flight response so a slow
	// reply can't land its diagnostics on newer (or cleared) text.
	$effect(() => {
		const text = source;
		const systemId = proof?.formal_system_id;
		if (!systemId) return;
		liveSeq++;
		liveVerifying = false;
		if (!text.trim()) {
			liveResult = null;
			liveError = null;
			return;
		}
		const timer = setTimeout(() => runLiveVerify(systemId, text), 450);
		return () => clearTimeout(timer);
	});

	// Persist the source, then record the authoritative verdict (which resolves any
	// saved lemma citations the live preview can't). Guards on the route id so a
	// busy flag always resets even if the user navigates away mid-save.
	async function saveSource() {
		if (!proof || savingSource || !dirty) return;
		const id = proof.id;
		savingSource = true;
		try {
			const updated = await api.proofs.update(id, { source });
			if (page.params.id !== id) return;
			proof = updated;
			const res = await api.proofs.verify(id);
			if (page.params.id !== id) return;
			proof = { ...proof, valid: res.proof ? res.success : null, result: res.proof };
			toastSuccess('Proof saved.');
		} catch (err) {
			if (page.params.id === id) toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			savingSource = false;
		}
	}

	async function saveDetails(event: SubmitEvent) {
		event.preventDefault();
		if (!proof || savingDetails || !name.trim()) return;
		const id = proof.id;
		savingDetails = true;
		try {
			const updated = await api.proofs.update(id, {
				name: name.trim(),
				description: description.trim() || null
			});
			if (page.params.id !== id) return;
			proof = updated;
			toastSuccess('Details saved.');
		} catch (err) {
			if (page.params.id === id) toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			savingDetails = false;
		}
	}

	async function togglePublish() {
		if (!proof || publishing) return;
		const id = proof.id;
		const next = proof.published_at === null;
		publishing = true;
		try {
			const updated = await api.proofs.update(id, { published: next });
			if (page.params.id !== id) return;
			proof = updated;
			toastSuccess(next ? 'Proof published.' : 'Proof unpublished.');
		} catch (err) {
			if (page.params.id === id) toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			publishing = false;
		}
	}

	async function confirmDelete() {
		if (!proof || deleting) return;
		const id = proof.id;
		deleting = true;
		try {
			await api.proofs.remove(id);
			if (page.params.id !== id) return;
			toastSuccess('Proof deleted.');
			goto('/proofs');
		} catch (err) {
			if (page.params.id === id) {
				toastError(err instanceof ApiError ? err.message : String(err));
				confirmOpen = false;
			}
		} finally {
			deleting = false;
		}
	}

	$effect(() => {
		const id = page.params.id;
		if (!id) return;
		if (!auth.ready) return;
		if (!auth.user) {
			goto(`/login?next=/proofs/${id}/edit`);
			return;
		}
		load(id);
	});
</script>

<PageContainer maxWidth="5xl" gap>
	<BackLink href={`/proofs/${page.params.id}`} label="Back to proof" />

	{#if loadError}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>Proof unavailable</Alert.Title>
			<Alert.Description>{loadError}</Alert.Description>
		</Alert.Root>
	{:else if !auth.ready || loading || !proof}
		<LoadingSpinner message="Loading proof…" />
	{:else if !isOwner}
		<Alert.Root>
			<TriangleAlert class="size-4" />
			<Alert.Title>Read-only</Alert.Title>
			<Alert.Description>
				You can only edit proofs you own. <a class="underline" href={`/proofs/${proof.id}`}>View this proof</a>.
			</Alert.Description>
		</Alert.Root>
	{:else}
		<PageHeader title="Edit proof" description={proof.name} />

		<!-- Two-pane workspace: write on the left, live line-by-line results on the right. -->
		<div class="grid items-start gap-6 lg:grid-cols-2">
			<Card.Root>
				<Card.Header>
					<div class="flex items-center justify-between gap-2">
						<Card.Title>Proof</Card.Title>
						<div class="text-xs text-muted-foreground">
							{#if liveVerifying}
								<span class="inline-flex items-center gap-1"><LoaderCircle class="size-3 animate-spin" /> Checking…</span>
							{:else if dirty}
								Unsaved changes
							{:else}
								Saved
							{/if}
						</div>
					</div>
					<Card.Description>One statement per line — checked live as you type.</Card.Description>
				</Card.Header>
				<Card.Content class="flex flex-col gap-3">
					<CodeEditor
						id="source"
						bind:value={source}
						bind:this={editor}
						rows={14}
						showLineNumbers
						{lineStatuses}
					/>
					<div class="flex justify-end">
						<Button onclick={saveSource} disabled={savingSource || !dirty}>
							{#if savingSource}
								<LoaderCircle class="size-4 animate-spin" /> Saving…
							{:else}
								<Save class="size-4" /> Save proof
							{/if}
						</Button>
					</div>
				</Card.Content>
			</Card.Root>

			<ProofResults
				result={liveResult}
				requestError={liveError}
				idleMessage="Start typing your proof to see line-by-line results here."
				onLineClick={(i) => editor?.focusLine(i)}
			/>
		</div>

		{#if proof.references.length > 0}
			<p class="text-xs text-muted-foreground">
				Live results check your text against the system. Cited lemmas (<code>[alias.line]</code>)
				resolve when you <strong>Save</strong>, which records the proof's validity.
			</p>
		{/if}

		<Card.Root>
			<Card.Header>
				<Card.Title>Details</Card.Title>
				<Card.Description>Name and description shown across the app.</Card.Description>
			</Card.Header>
			<Card.Content>
				<form class="flex flex-col gap-4" onsubmit={saveDetails}>
					<div class="flex flex-col gap-2">
						<Label for="name">Name</Label>
						<Input id="name" bind:value={name} maxlength={256} required />
					</div>
					<div class="flex flex-col gap-2">
						<Label for="description">Description <span class="text-muted-foreground">(optional)</span></Label>
						<Textarea id="description" bind:value={description} rows={2} />
					</div>
					<div class="flex justify-end">
						<Button type="submit" variant="outline" disabled={savingDetails || !detailsDirty || name.trim().length === 0}>
							{#if savingDetails}
								<LoaderCircle class="size-4 animate-spin" /> Saving…
							{:else}
								Save details
							{/if}
						</Button>
					</div>
				</form>
			</Card.Content>
		</Card.Root>

		<LemmasPanel
			{proof}
			onUpdated={(updated) => {
				proof = updated;
			}}
		/>

		<Card.Root>
			<Card.Header>
				<Card.Title>Visibility</Card.Title>
				<Card.Description>
					Published proofs appear in the public list for everyone; drafts are visible only to you. A proof
					can only be published once it verifies and its system is published.
				</Card.Description>
			</Card.Header>
			<Card.Content class="flex items-center justify-between gap-4">
				<div class="flex items-center gap-2">
					<StatusBadge status={proof.published_at ? 'published' : 'draft'} />
					<CheckBadge valid={proof.valid} />
				</div>
				<Button variant="outline" onclick={togglePublish} disabled={publishing}>
					{#if publishing}
						<LoaderCircle class="size-4 animate-spin" />
					{/if}
					{proof.published_at ? 'Unpublish' : 'Publish'}
				</Button>
			</Card.Content>
		</Card.Root>

		<Card.Root class="border-destructive/40">
			<Card.Header>
				<Card.Title>Danger zone</Card.Title>
				<Card.Description>Deleting a proof removes it permanently. This cannot be undone.</Card.Description>
			</Card.Header>
			<Card.Content>
				<Button variant="destructive" onclick={() => (confirmOpen = true)}>
					<Trash2 class="size-4" /> Delete proof
				</Button>
			</Card.Content>
		</Card.Root>

		<ConfirmDialog
			bind:open={confirmOpen}
			title="Delete this proof?"
			description={`"${proof.name}" will be permanently deleted.`}
			confirmLabel="Delete"
			variant="destructive"
			loading={deleting}
			onConfirm={confirmDelete}
			onCancel={() => (confirmOpen = false)}
		/>
	{/if}
</PageContainer>
