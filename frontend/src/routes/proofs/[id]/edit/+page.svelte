<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Textarea } from '$lib/components/ui/textarea';
	import CodeEditor from '$lib/components/code-editor.svelte';
	import * as Card from '$lib/components/ui/card';
	import * as Alert from '$lib/components/ui/alert';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import BackLink from '$lib/components/BackLink.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import CheckBadge from '$lib/components/CheckBadge.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import ProofResults from '$lib/components/ProofResults.svelte';
	import LemmasPanel from '$lib/components/LemmasPanel.svelte';
	import { api, ApiError, type ProofDetail, type VerifyResponse } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { toastSuccess, toastError } from '$lib/toast';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import Play from '@lucide/svelte/icons/play';
	import Trash2 from '@lucide/svelte/icons/trash-2';

	let proof = $state<ProofDetail | null>(null);
	let loading = $state(true);
	let loadError = $state<string | null>(null);

	let name = $state('');
	let description = $state('');
	let source = $state('');
	let saving = $state(false);
	let publishing = $state(false);

	let verifying = $state(false);
	let result = $state<VerifyResponse | null>(null);
	let requestError = $state<string | null>(null);

	let confirmOpen = $state(false);
	let deleting = $state(false);

	let loadSeq = 0;

	const isOwner = $derived(!!auth.user && !!proof && proof.owner?.id === auth.user.id);
	// Warn when the editor has changes not yet saved — verify checks the *saved*
	// source, so the two can disagree until a save.
	const dirty = $derived(!!proof && source !== proof.source);

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
			result = detail.result
				? { success: detail.valid ?? false, errors: [], proof: detail.result }
				: null;
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

	// Mutations guard on the route id (not loadSeq) so a busy flag always resets
	// and a terminal delete always navigates, mirroring the system editor.
	async function saveDetails(event: SubmitEvent) {
		event.preventDefault();
		if (!proof || saving || !name.trim()) return;
		const id = proof.id;
		saving = true;
		try {
			const updated = await api.proofs.update(id, {
				name: name.trim(),
				description: description.trim() || null,
				source
			});
			if (page.params.id !== id) return;
			proof = updated;
			// Editing the source clears the server-side verdict; reflect that here.
			result = null;
			toastSuccess('Changes saved.');
		} catch (err) {
			if (page.params.id === id) toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			saving = false;
		}
	}

	async function verify() {
		if (!proof) return;
		const id = proof.id;
		verifying = true;
		requestError = null;
		try {
			const res = await api.proofs.verify(id);
			if (page.params.id !== id) return;
			result = res;
			// Reflect the freshly cached verdict on the status badge.
			if (proof) proof = { ...proof, valid: res.proof ? res.success : null };
		} catch (err) {
			if (page.params.id === id) requestError = err instanceof ApiError ? err.message : String(err);
		} finally {
			verifying = false;
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

<PageContainer maxWidth="3xl" gap>
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
					<div class="flex flex-col gap-2">
						<Label for="source">Proof</Label>
						<CodeEditor id="source" bind:value={source} rows={10} />
					</div>
					<div class="flex justify-end">
						<Button type="submit" disabled={saving || name.trim().length === 0}>
							{#if saving}
								<LoaderCircle class="size-4 animate-spin" /> Saving…
							{:else}
								Save changes
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
				// A reference change clears the server-side verdict; drop the stale result.
				result = null;
			}}
		/>

		<!-- Verification runs against the last *saved* source. -->
		<div class="flex flex-col gap-3">
			<div class="flex items-center gap-3">
				<Button variant="outline" onclick={verify} disabled={verifying}>
					{#if verifying}
						<LoaderCircle class="size-4 animate-spin" /> Verifying…
					{:else}
						<Play class="size-4" /> Verify saved proof
					{/if}
				</Button>
				{#if dirty}
					<span class="text-xs text-warning">Unsaved edits — save before verifying.</span>
				{/if}
			</div>
			<ProofResults {result} {requestError} idleMessage="Verify to check the saved proof against its system." />
		</div>

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
