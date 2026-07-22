<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
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
	import { api, ApiError, type FormalSystemSummary } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { toastSuccess, toastError } from '$lib/toast';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';

	// A proof must be attached to a system the caller can use: their own systems,
	// or any published one. Offer both, grouped, with owned systems first.
	let ownSystems = $state<FormalSystemSummary[]>([]);
	let publicSystems = $state<FormalSystemSummary[]>([]);
	let loadingSystems = $state(true);
	let loadError = $state<string | null>(null);

	// A published system not owned by the caller is still selectable; dedupe so an
	// owned-and-published system isn't offered twice.
	const publicOnly = $derived(
		publicSystems.filter((s) => !ownSystems.some((o) => o.id === s.id))
	);
	const hasSystems = $derived(ownSystems.length > 0 || publicOnly.length > 0);

	let systemId = $state('');
	let name = $state('');
	let description = $state('');
	let source = $state('');
	let saving = $state(false);
	let error = $state<string | null>(null);

	// Creating requires an account; bounce to login and come back.
	$effect(() => {
		if (auth.ready && !auth.user) goto('/login?next=/proofs/new');
	});

	$effect(() => {
		if (auth.ready && auth.user) loadSystems();
	});

	async function loadSystems() {
		loadingSystems = true;
		loadError = null;
		try {
			const [own, pub] = await Promise.all([api.systems.list(), api.systems.listPublic()]);
			ownSystems = own;
			publicSystems = pub;
			// Preselect: a ?system= param (e.g. linked from a system page), else the
			// first available option.
			const preset = page.url.searchParams.get('system');
			const all = [...own, ...pub];
			if (preset && all.some((s) => s.id === preset)) systemId = preset;
			else if (!systemId && all.length > 0) systemId = all[0].id;
		} catch (err) {
			loadError = err instanceof ApiError ? err.message : String(err);
		} finally {
			loadingSystems = false;
		}
	}

	async function create(event: SubmitEvent) {
		event.preventDefault();
		if (!name.trim() || !systemId || saving) return;
		saving = true;
		error = null;
		try {
			const created = await api.proofs.create({
				name: name.trim(),
				formal_system_id: systemId,
				description: description.trim() || null,
				source
			});
			toastSuccess('Proof created.');
			goto(`/proofs/${created.id}`);
		} catch (err) {
			error = err instanceof ApiError ? err.message : String(err);
			toastError('Could not create proof.');
			saving = false;
		}
	}
</script>

<PageContainer maxWidth="2xl" gap>
	<BackLink href="/proofs" label="All proofs" />
	<PageHeader title="New proof" description="Pick a system, then write your proof against it." />

	{#if loadingSystems}
		<LoadingSpinner message="Loading systems…" />
	{:else if loadError}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>Could not load systems</Alert.Title>
			<Alert.Description>{loadError}</Alert.Description>
		</Alert.Root>
	{:else if !hasSystems}
		<Alert.Root>
			<TriangleAlert class="size-4" />
			<Alert.Title>No systems available</Alert.Title>
			<Alert.Description>
				A proof is checked against a formal system. <a class="underline" href="/systems/new">Create a system</a>
				first, or browse <a class="underline" href="/systems">published systems</a>.
			</Alert.Description>
		</Alert.Root>
	{:else}
		<Card.Root>
			<Card.Content class="pt-6">
				<form class="flex flex-col gap-4" onsubmit={create}>
					{#if error}
						<Alert.Root variant="destructive">
							<TriangleAlert class="size-4" />
							<Alert.Description>{error}</Alert.Description>
						</Alert.Root>
					{/if}
					<div class="flex flex-col gap-2">
						<Label for="system">System</Label>
						<select
							id="system"
							bind:value={systemId}
							required
							class="border-input focus-visible:ring-ring flex h-9 w-full rounded-md border bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1"
						>
							{#if ownSystems.length}
								<optgroup label="My systems">
									{#each ownSystems as s (s.id)}
										<option value={s.id}>{s.name}</option>
									{/each}
								</optgroup>
							{/if}
							{#if publicOnly.length}
								<optgroup label="Published">
									{#each publicOnly as s (s.id)}
										<option value={s.id}>{s.name}</option>
									{/each}
								</optgroup>
							{/if}
						</select>
					</div>
					<div class="flex flex-col gap-2">
						<Label for="name">Name</Label>
						<Input id="name" bind:value={name} placeholder="e.g. Reflexivity of equality" maxlength={256} required />
					</div>
					<div class="flex flex-col gap-2">
						<Label for="description">Description <span class="text-muted-foreground">(optional)</span></Label>
						<Textarea id="description" bind:value={description} rows={2} placeholder="What does this proof establish?" />
					</div>
					<div class="flex flex-col gap-2">
						<Label for="source">Proof <span class="text-muted-foreground">(optional — you can add it later)</span></Label>
						<CodeEditor id="source" bind:value={source} rows={8} />
					</div>
					<div class="flex justify-end gap-2">
						<Button type="button" variant="ghost" href="/proofs">Cancel</Button>
						<Button type="submit" disabled={saving || name.trim().length === 0 || !systemId}>
							{#if saving}
								<LoaderCircle class="size-4 animate-spin" /> Creating…
							{:else}
								Create proof
							{/if}
						</Button>
					</div>
				</form>
			</Card.Content>
		</Card.Root>
	{/if}
</PageContainer>
