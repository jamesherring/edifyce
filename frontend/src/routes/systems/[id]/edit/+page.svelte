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
	import CompileStatus from './CompileStatus.svelte';
	import SystemOutline, { type OutlineSection } from './SystemOutline.svelte';
	import {
		api,
		ApiError,
		type FormalSystemDetail,
		type SystemValidation
	} from '$lib/api';
	import { systemSymbols } from '$lib/symbols';
	import { notationReference } from '$lib/notation';
	import { createUnsavedGuard } from '$lib/unsaved-guard.svelte';
	import { auth } from '$lib/auth.svelte';
	import { toastSuccess, toastError } from '$lib/toast';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import Trash2 from '@lucide/svelte/icons/trash-2';
	import Lock from '@lucide/svelte/icons/lock';

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
	// The system's own notation, offered by each edit sheet's symbol palette, and
	// the grammar reference shown beside it.
	const symbols = $derived(systemSymbols(system));
	const notation = $derived(notationReference(system));

	// Only the details form defers its save — every part saves from its own sheet
	// the moment you confirm it — so that's all this guards.
	const detailsDirty = $derived(
		!!system &&
			(name.trim() !== system.name ||
				(description.trim() || null) !== (system.description ?? null))
	);
	const guard = createUnsavedGuard(() => detailsDirty);

	// The outline's table of contents. Ids double as the sections' scroll anchors.
	const outline = $derived<OutlineSection[]>(
		system
			? [
					{ id: 'sorts', title: 'Sorts', count: system.sorts.length },
					{ id: 'brackets', title: 'Brackets', count: system.brackets.length },
					{ id: 'grammar', title: 'Grammar', count: system.productions.length },
					{ id: 'line-types', title: 'Line types', count: system.lines.length },
					{ id: 'axioms', title: 'Axioms', count: system.axioms.length },
					{ id: 'rules', title: 'Inference rules', count: system.rules.length },
					{ id: 'definitions', title: 'Definitions', count: system.definitions.length }
				]
			: []
	);

	// hydrateForm is only true on the initial load / route change, so refetching
	// after a part edit can't clobber unsaved name/description edits. All state
	// writes are gated on `seq` so a superseded fetch (fast A→B→C navigation)
	// never overwrites the latest system, its loading flag, or its validation.
	async function fetchInto(id: string, seq: number, hydrateForm: boolean): Promise<boolean> {
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
		const seq = ++loadSeq;
		loading = true;
		loadError = null;
		const ok = await fetchInto(id, seq, true);
		if (seq !== loadSeq) return; // a newer load now owns the page state
		loading = false;
		if (ok) runValidation(id, seq);
	}

	// Called by the part sections after any change: refresh the aggregate (without
	// touching the settings form) and re-check that the system still compiles.
	async function refresh() {
		if (!system) return;
		const id = system.id;
		const seq = ++loadSeq;
		const ok = await fetchInto(id, seq, false);
		if (ok && seq === loadSeq) runValidation(id, seq);
	}

	async function runValidation(id: string, seq: number) {
		validating = true;
		try {
			const result = await api.systems.validate(id);
			if (seq !== loadSeq) return;
			validation = result;
		} catch (err) {
			if (seq !== loadSeq) return;
			validation = {
				success: false,
				errors: [err instanceof ApiError ? err.message : String(err)],
				system_name: null,
				line_type_count: null,
				inference_rule_count: null
			};
		} finally {
			if (seq === loadSeq) validating = false;
		}
	}

	// System-level mutations guard on the route id (`page.params.id`), NOT on
	// `loadSeq`. A part edit fires refresh() → ++loadSeq while a save/publish is
	// in flight; gating on loadSeq would then strand the busy flag on (a spinner
	// that never resets) and skip the terminal delete's navigation. The only
	// thing a mutation must not do after its await is apply a result to a system
	// the user has since navigated away from — that's what `page.params.id`
	// tracks, and the busy flag always resets regardless.
	async function saveDetails(event: SubmitEvent) {
		event.preventDefault();
		if (!system || saving || !name.trim()) return;
		const id = system.id;
		saving = true;
		try {
			const updated = await api.systems.update(id, {
				name: name.trim(),
				description: description.trim() || null
			});
			if (page.params.id !== id) return; // navigated to another system mid-flight
			system = updated;
			toastSuccess('Changes saved.');
		} catch (err) {
			if (page.params.id === id) toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			saving = false;
		}
	}

	// Publishing is one-way: a published system is frozen (this control only
	// renders for drafts), so there's no unpublish path.
	async function publish() {
		if (!system || publishing) return;
		const id = system.id;
		publishing = true;
		try {
			const updated = await api.systems.update(id, { published: true });
			if (page.params.id !== id) return;
			system = updated;
			toastSuccess('System published.');
		} catch (err) {
			if (page.params.id === id) toastError(err instanceof ApiError ? err.message : String(err));
		} finally {
			publishing = false;
		}
	}

	async function confirmDelete() {
		if (!system || deleting) return;
		const id = system.id;
		deleting = true;
		try {
			await api.systems.remove(id);
			// Navigate away only while still viewing the system we deleted — never
			// strand the user on a now-deleted system, but don't yank them off a
			// different one they navigated to before the DELETE resolved. Guarding
			// on the route id (not loadSeq) keeps the strand fixed: a part refresh
			// bumps loadSeq but leaves page.params.id unchanged.
			if (page.params.id !== id) return;
			toastSuccess('System deleted.');
			guard.allow();
			goto('/systems');
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
		// Wait for auth to resolve before loading. Loading earlier would flash the
		// "read-only" alert to the owner (isOwner is false until `/users/me`
		// lands) and, once auth flips, re-run this effect → a second load() and a
		// redundant full recompile on every open.
		if (!auth.ready) return;
		if (!auth.user) {
			goto(`/login?next=/systems/${id}/edit`);
			return;
		}
		load(id);
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
	{:else if !auth.ready || loading || !system}
		<LoadingSpinner message="Loading system…" />
	{:else if !isOwner}
		<Alert.Root>
			<TriangleAlert class="size-4" />
			<Alert.Title>Read-only</Alert.Title>
			<Alert.Description>
				You can only edit systems you own. <a class="underline" href={`/systems/${system.id}`}>View this system</a>.
			</Alert.Description>
		</Alert.Root>
	{:else if system.published_at}
		<!-- Published systems are frozen: nothing here is editable, and they can't
		     be unpublished (so proofs verified against them stay valid). Only the
		     destructive delete remains available. -->
		<PageHeader title="Edit system" description={system.name} />

		<Alert.Root>
			<Lock class="size-4" />
			<Alert.Title>This system is published</Alert.Title>
			<Alert.Description>
				Published systems are frozen so that proofs verified against them stay valid — they
				can't be edited or unpublished. <a class="underline" href={`/systems/${system.id}`}>View the system</a>.
			</Alert.Description>
		</Alert.Root>

		<Card.Root class="border-destructive/40">
			<Card.Header>
				<Card.Title>Danger zone</Card.Title>
				<Card.Description>Deleting a system removes it and all its contents (including its proofs). This cannot be undone.</Card.Description>
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
	{:else}
		<PageHeader title="Edit system" description={system.name} />

		<Card.Root>
			<Card.Header>
				<div class="flex items-center justify-between gap-2">
					<Card.Title>Details</Card.Title>
					<div class="text-muted-foreground text-xs">
						{#if saving}
							<span class="inline-flex items-center gap-1">
								<LoaderCircle class="size-3 animate-spin" /> Saving…
							</span>
						{:else if detailsDirty}
							Unsaved changes
						{:else}
							Saved
						{/if}
					</div>
				</div>
				<Card.Description>
					Name and description shown across the app. These save when you press Save changes;
					everything below saves as soon as you confirm it.
				</Card.Description>
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
						<Button type="submit" disabled={saving || !detailsDirty || name.trim().length === 0}>
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

		<!-- Wide screens get the outline and the compile status pinned beside the
		     contents, so neither scrolls out of reach while editing a long system. -->
		<div class="lg:grid lg:grid-cols-[13rem_minmax(0,1fr)] lg:items-start lg:gap-8">
			<aside class="hidden lg:sticky lg:top-20 lg:block">
				<SystemOutline sections={outline} {validation} {validating} />
			</aside>

			<div class="space-y-4">
				<!-- Live compile status; refreshed after every part change. Narrow
				     screens have no sidebar to pin it in, so it leads the contents. -->
				<div class="lg:hidden">
					<CompileStatus {validation} {validating} />
				</div>

				<SortsSection systemId={system.id} sorts={system.sorts} onChanged={refresh} />
				<BracketsSection systemId={system.id} brackets={system.brackets} {symbols} {notation} onChanged={refresh} />
				<ProductionsSection systemId={system.id} productions={system.productions} {sortNames} {symbols} {notation} onChanged={refresh} />
				<LineTypesSection systemId={system.id} lines={system.lines} {sortNames} {symbols} {notation} onChanged={refresh} />
				<AxiomsSection systemId={system.id} axioms={system.axioms} {symbols} {notation} onChanged={refresh} />
				<RulesSection systemId={system.id} rules={system.rules} {symbols} {notation} onChanged={refresh} />
				<DefinitionsSection systemId={system.id} definitions={system.definitions} {sortNames} {symbols} {notation} onChanged={refresh} />
			</div>
		</div>

		<Card.Root>
			<Card.Header>
				<Card.Title>Visibility</Card.Title>
				<Card.Description>
					Publishing lists the system publicly for everyone. It's permanent: a published system
					is frozen — it can't be edited or unpublished — so proofs verified against it stay valid.
				</Card.Description>
			</Card.Header>
			<Card.Content class="flex items-center justify-between gap-4">
				<StatusBadge status="draft" />
				<Button variant="outline" onclick={publish} disabled={publishing}>
					{#if publishing}
						<LoaderCircle class="size-4 animate-spin" />
					{/if}
					Publish
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
			open={guard.prompting}
			title="Leave without saving?"
			description="The system details have changes you haven't saved. They'll be lost if you leave now."
			confirmLabel="Leave"
			variant="destructive"
			onConfirm={guard.leave}
			onCancel={guard.stay}
		/>

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
