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
	import SortsSection from './SortsSection.svelte';
	import BracketsSection from './BracketsSection.svelte';
	import ProductionsSection from './ProductionsSection.svelte';
	import LineTypesSection from './LineTypesSection.svelte';
	import DefinitionsSection from './DefinitionsSection.svelte';
	import AxiomsSection from './AxiomsSection.svelte';
	import RulesSection from './RulesSection.svelte';
	import {
		api,
		ApiError,
		type FormalSystemDetail,
		type SystemValidation
	} from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { toastSuccess, toastError } from '$lib/toast';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import CircleCheck from '@lucide/svelte/icons/circle-check-big';
	import CircleX from '@lucide/svelte/icons/circle-x';
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

	let validation = $state<SystemValidation | null>(null);
	let validating = $state(false);

	let loadSeq = 0;

	const isOwner = $derived(!!auth.user && !!system && system.owner?.id === auth.user.id);
	const sortNames = $derived(system ? system.sorts.map((s) => s.name) : []);

	// hydrateForm is only true on the initial load / route change, so refetching
	// after a part edit can't clobber unsaved name/description edits.
	async function fetchSystem(id: string, hydrateForm: boolean): Promise<boolean> {
		const seq = ++loadSeq;
		try {
			const detail = await api.systems.get(id);
			if (seq !== loadSeq) return false;
			system = detail;
			if (hydrateForm) {
				name = detail.name;
				description = detail.description ?? '';
			}
			return true;
		} catch (err) {
			if (seq !== loadSeq) return false;
			loadError =
				err instanceof ApiError
					? err.status === 404
						? 'This system does not exist, or is a private draft.'
						: err.message
					: String(err);
			system = null;
			return false;
		}
	}

	async function load(id: string) {
		loading = true;
		loadError = null;
		const ok = await fetchSystem(id, true);
		loading = false;
		if (ok) runValidation(id);
	}

	// Called by the part sections after any change: refresh the aggregate (without
	// touching the settings form) and re-check that the system still compiles.
	async function refresh() {
		if (!system) return;
		const id = system.id;
		await fetchSystem(id, false);
		await runValidation(id);
	}

	async function runValidation(id: string) {
		validating = true;
		try {
			validation = await api.systems.validate(id);
		} catch (err) {
			validation = {
				success: false,
				errors: [err instanceof ApiError ? err.message : String(err)],
				system_name: null,
				line_type_count: null,
				inference_rule_count: null
			};
		} finally {
			validating = false;
		}
	}

	async function saveDetails(event: SubmitEvent) {
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
		if (auth.ready && !auth.user) {
			goto(`/login?next=/systems/${id}/edit`);
			return;
		}
		load(id);
	});
</script>

<PageContainer maxWidth="3xl" gap>
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
				<form class="flex flex-col gap-4" onsubmit={saveDetails}>
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

		<!-- Live compile status; refreshed after every part change. -->
		{#if validating && !validation}
			<div class="rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">Checking…</div>
		{:else if validation}
			{#if validation.success}
				<Alert.Root variant="success">
					<CircleCheck class="size-4" />
					<Alert.Title>Compiles cleanly</Alert.Title>
					<Alert.Description>
						{validation.line_type_count ?? 0} line type(s), {validation.inference_rule_count ?? 0} inference rule(s).
					</Alert.Description>
				</Alert.Root>
			{:else}
				<Alert.Root variant="destructive">
					<CircleX class="size-4" />
					<Alert.Title>Does not compile ({validation.errors.length})</Alert.Title>
					<Alert.Description>
						<ul class="mt-1 space-y-1">
							{#each validation.errors as err (err)}
								<li class="rounded border border-destructive/30 bg-destructive/5 px-2 py-1 font-mono text-xs">
									{err}
								</li>
							{/each}
						</ul>
					</Alert.Description>
				</Alert.Root>
			{/if}
		{/if}

		<!-- Contents: the notation, grammar, rules and definitions. -->
		<div class="space-y-4">
			<SortsSection systemId={system.id} sorts={system.sorts} onChanged={refresh} />
			<BracketsSection systemId={system.id} brackets={system.brackets} onChanged={refresh} />
			<ProductionsSection systemId={system.id} productions={system.productions} {sortNames} onChanged={refresh} />
			<LineTypesSection systemId={system.id} lines={system.lines} {sortNames} onChanged={refresh} />
			<AxiomsSection systemId={system.id} axioms={system.axioms} onChanged={refresh} />
			<RulesSection systemId={system.id} rules={system.rules} onChanged={refresh} />
			<DefinitionsSection systemId={system.id} definitions={system.definitions} {sortNames} onChanged={refresh} />
		</div>

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
