<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Textarea } from '$lib/components/ui/textarea';
	import * as Card from '$lib/components/ui/card';
	import * as Alert from '$lib/components/ui/alert';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import BackLink from '$lib/components/BackLink.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import { api, ApiError, type FormalSystemDetail } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { toastSuccess, toastError } from '$lib/toast';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import Trash2 from '@lucide/svelte/icons/trash-2';

	let system = $state<FormalSystemDetail | null>(null);
	let loading = $state(true);
	let loadError = $state<string | null>(null);

	let name = $state('');
	let description = $state('');
	let saving = $state(false);
	let publishing = $state(false);

	let confirmOpen = $state(false);
	let deleting = $state(false);

	let loadSeq = 0;

	const isOwner = $derived(!!auth.user && !!system && system.owner?.id === auth.user.id);

	async function load(id: string) {
		const seq = ++loadSeq;
		loading = true;
		loadError = null;
		try {
			const detail = await api.systems.get(id);
			if (seq !== loadSeq) return;
			system = detail;
			name = detail.name;
			description = detail.description ?? '';
		} catch (err) {
			if (seq !== loadSeq) return;
			loadError =
				err instanceof ApiError
					? err.status === 404
						? 'This system does not exist, or is a private draft.'
						: err.message
					: String(err);
			system = null;
		} finally {
			if (seq === loadSeq) loading = false;
		}
	}

	async function save(event: SubmitEvent) {
		event.preventDefault();
		if (!system || saving || !name.trim()) return;
		saving = true;
		try {
			system = await api.systems.update(system.id, {
				name: name.trim(),
				description: description.trim() || null
			});
			toastSuccess('Changes saved.');
		} catch (err) {
			toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			saving = false;
		}
	}

	async function togglePublish() {
		if (!system || publishing) return;
		const next = system.published_at === null;
		publishing = true;
		try {
			system = await api.systems.update(system.id, { published: next });
			toastSuccess(next ? 'System published.' : 'System unpublished.');
		} catch (err) {
			toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			publishing = false;
		}
	}

	async function confirmDelete() {
		if (!system || deleting) return;
		deleting = true;
		try {
			await api.systems.remove(system.id);
			toastSuccess('System deleted.');
			goto('/systems');
		} catch (err) {
			toastError(err instanceof ApiError ? err.message : String(err));
			deleting = false;
			confirmOpen = false;
		}
	}

	$effect(() => {
		const id = page.params.id;
		if (!id) return;
		// Editing needs an account; send guests to login and back.
		if (auth.ready && !auth.user) {
			goto(`/login?next=/systems/${id}/edit`);
			return;
		}
		load(id);
	});
</script>

<PageContainer maxWidth="2xl" gap>
	<BackLink href={`/systems/${page.params.id}`} label="Back to system" />

	{#if loadError}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>System unavailable</Alert.Title>
			<Alert.Description>{loadError}</Alert.Description>
		</Alert.Root>
	{:else if loading || !system}
		<LoadingSpinner message="Loading system…" />
	{:else if !isOwner}
		<Alert.Root>
			<TriangleAlert class="size-4" />
			<Alert.Title>Read-only</Alert.Title>
			<Alert.Description>
				You can only edit systems you own. <a class="underline" href={`/systems/${system.id}`}>View this system</a>.
			</Alert.Description>
		</Alert.Root>
	{:else}
		<PageHeader title="Edit system" description={system.name} />

		<Card.Root>
			<Card.Header>
				<Card.Title>Details</Card.Title>
				<Card.Description>Name and description shown across the app.</Card.Description>
			</Card.Header>
			<Card.Content>
				<form class="flex flex-col gap-4" onsubmit={save}>
					<div class="flex flex-col gap-2">
						<Label for="name">Name</Label>
						<Input id="name" bind:value={name} maxlength={256} required />
					</div>
					<div class="flex flex-col gap-2">
						<Label for="description">Description <span class="text-muted-foreground">(optional)</span></Label>
						<Textarea id="description" bind:value={description} rows={3} />
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

		<Card.Root>
			<Card.Header>
				<Card.Title>Visibility</Card.Title>
				<Card.Description>
					Published systems appear in the public list for everyone; drafts are visible only to you.
				</Card.Description>
			</Card.Header>
			<Card.Content class="flex items-center justify-between gap-4">
				<StatusBadge status={system.published_at ? 'published' : 'draft'} />
				<Button variant="outline" onclick={togglePublish} disabled={publishing}>
					{#if publishing}
						<LoaderCircle class="size-4 animate-spin" />
					{/if}
					{system.published_at ? 'Unpublish' : 'Publish'}
				</Button>
			</Card.Content>
		</Card.Root>

		<Card.Root class="border-destructive/40">
			<Card.Header>
				<Card.Title>Danger zone</Card.Title>
				<Card.Description>Deleting a system removes it and all its contents. This cannot be undone.</Card.Description>
			</Card.Header>
			<Card.Content>
				<Button variant="destructive" onclick={() => (confirmOpen = true)}>
					<Trash2 class="size-4" /> Delete system
				</Button>
			</Card.Content>
		</Card.Root>

		<ConfirmDialog
			bind:open={confirmOpen}
			title="Delete this system?"
			description={`"${system.name}" and all its notation, rules and definitions will be permanently deleted.`}
			confirmLabel="Delete"
			variant="destructive"
			loading={deleting}
			onConfirm={confirmDelete}
			onCancel={() => (confirmOpen = false)}
		/>
	{/if}
</PageContainer>
