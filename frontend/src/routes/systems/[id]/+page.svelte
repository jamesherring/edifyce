<script lang="ts">
	import { page } from '$app/state';
	import PageContainer from '$lib/components/PageContainer.svelte';
	import EntityHeader from '$lib/components/EntityHeader.svelte';
	import EntityFooter from '$lib/components/EntityFooter.svelte';
	import BackLink from '$lib/components/BackLink.svelte';
	import SectionCard from '$lib/components/SectionCard.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import LoadingSpinner from '$lib/components/LoadingSpinner.svelte';
	import { Button } from '$lib/components/ui/button';
	import * as Alert from '$lib/components/ui/alert';
	import SystemParts from './SystemParts.svelte';
	import OutlineTree from '$lib/components/OutlineTree.svelte';
	import FolderProofs from './FolderProofs.svelte';
	import { auth } from '$lib/auth.svelte';
	import {
		api,
		ApiError,
		type Folder,
		type WorkCited,
		type FormalSystemDetail,
		type SystemValidation
	} from '$lib/api';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import CircleCheck from '@lucide/svelte/icons/circle-check-big';
	import CircleX from '@lucide/svelte/icons/circle-x';
	import SquareCheck from '@lucide/svelte/icons/square-check-big';
	import Pencil from '@lucide/svelte/icons/pencil';
	import Layers from '@lucide/svelte/icons/layers';
	import BookMarked from '@lucide/svelte/icons/book-marked';
	import CircleHelp from '@lucide/svelte/icons/circle-help';

	let system = $state<FormalSystemDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let validation = $state<SystemValidation | null>(null);
	let validating = $state(false);

	// The system's folder tree. For an imported corpus this is the outline its
	// `.mm` file draws with section headers; a hand-authored system has none, and
	// the card simply does not appear.
	let outline = $state<Folder[]>([]);
	// The literature this system's prose cites. Empty for a hand-authored system,
	// and for an imported one whose comments name no sources — the button simply
	// does not appear.
	let works = $state<WorkCited[]>([]);
	// What this system takes on without proving. Counted rather than listed here:
	// the number is the interesting part on a system's front page, and a system
	// that assumes nothing should say so to its owner rather than hide the door.
	let assumed = $state(0);
	// Which section of it is being read, or null for none picked yet.
	let selectedFolder = $state<Folder | null>(null);

	// Bumped on every load so late responses from a previous id (system or
	// validation) are dropped instead of overwriting the current one.
	let requestSeq = 0;

	async function load(id: string) {
		const seq = ++requestSeq;
		loading = true;
		error = null;
		validation = null;
		outline = [];
		works = [];
		assumed = 0;
		selectedFolder = null;
		let detail: FormalSystemDetail;
		try {
			detail = await api.systems.get(id);
		} catch (err) {
			if (seq !== requestSeq) return;
			error =
				err instanceof ApiError
					? err.status === 404
						? 'This system does not exist, or is a private draft.'
						: err.message
					: String(err);
			system = null;
			loading = false;
			return;
		}
		if (seq !== requestSeq) return;
		system = detail;
		loading = false;
		runValidation(id, seq);
		void loadOutline(id, seq);
		void loadWorks(id, seq);
		void loadAssumptions(id, seq);
	}

	async function loadAssumptions(id: string, seq: number) {
		try {
			const taken = await api.assumptions.list(id);
			if (seq === requestSeq) assumed = taken.length;
		} catch {
			// Best-effort, as the works are. The owner's door in does not depend on
			// this having answered.
		}
	}

	async function loadWorks(id: string, seq: number) {
		try {
			const cited = await api.systems.works(id);
			if (seq === requestSeq) works = cited;
		} catch {
			// Best-effort, as the outline is: a system that cites nothing and one
			// whose citations could not be read both show no button.
		}
	}

	async function loadOutline(id: string, seq: number) {
		try {
			const folders = await api.systems.folders(id);
			if (seq === requestSeq) outline = folders;
		} catch {
			// Best-effort: a system with no outline and a system whose outline could
			// not be read both show no card, and neither is worth an error banner
			// over the system itself.
		}
	}

	async function runValidation(id: string, seq: number) {
		validating = true;
		try {
			const result = await api.systems.validate(id);
			if (seq !== requestSeq) return;
			validation = result;
		} catch (err) {
			if (seq !== requestSeq) return;
			validation = {
				success: false,
				errors: [err instanceof ApiError ? err.message : String(err)],
				system_name: null,
				line_type_count: null,
				inference_rule_count: null,
				definitions: []
			};
		} finally {
			if (seq === requestSeq) validating = false;
		}
	}

	const isOwner = $derived(!!auth.user && !!system && system.owner?.id === auth.user.id);

	// Re-load whenever the route id changes.
	$effect(() => {
		const id = page.params.id;
		if (id) load(id);
	});
</script>

<svelte:head><title>{system?.name ?? 'System'} — Edifyce</title></svelte:head>

<PageContainer maxWidth="5xl" gap>
	<BackLink href="/systems" label="All systems" />

	{#if error}
		<Alert.Root variant="destructive">
			<TriangleAlert class="size-4" />
			<Alert.Title>System unavailable</Alert.Title>
			<Alert.Description>{error}</Alert.Description>
		</Alert.Root>
	{:else if loading || !system}
		<LoadingSpinner message="Loading system…" />
	{:else}
		<EntityHeader title={system.name} subtitle={system.description ?? undefined}>
			{#snippet badges()}
				<StatusBadge status={system?.published_at ? 'published' : 'draft'} />
				{#if system?.owner?.display_name}
					<span class="text-xs text-muted-foreground">by {system.owner.display_name}</span>
				{/if}
			{/snippet}
			{#snippet actions()}
				<div class="flex flex-wrap gap-2">
					{#if isOwner}
						<Button href={`/systems/${system?.id}/edit`} variant="outline" size="sm">
							<Pencil class="size-4" /> Edit
						</Button>
					{/if}
					<Button href={`/systems/${system?.id}/verify`} variant="outline" size="sm">
						<SquareCheck class="size-4" /> Verify a proof
					</Button>
					{#if system?.definitions.length}
						<Button href={`/systems/${system?.id}/definitions`} variant="outline" size="sm">
							<Layers class="size-4" /> Definitions
						</Button>
					{/if}
					{#if works.length}
						<Button href={`/systems/${system?.id}/works`} variant="outline" size="sm">
							<BookMarked class="size-4" /> Works cited
						</Button>
					{/if}
					{#if assumed > 0 || isOwner}
						<Button href={`/systems/${system?.id}/assumptions`} variant="outline" size="sm">
							<CircleHelp class="size-4" />
							Assumptions{assumed > 0 ? ` (${assumed})` : ''}
						</Button>
					{/if}
					{#if isOwner}
						<Button href={`/proofs/new?system=${system?.id}`} variant="outline" size="sm">
							<Pencil class="size-4" /> New proof
						</Button>
					{/if}
				</div>
			{/snippet}
		</EntityHeader>

		<!-- Validation: assemble the stored rows and compile, surfacing any errors. -->
		{#if validating}
			<SectionCard variant="muted">
				<p class="text-sm text-muted-foreground">Checking the system compiles…</p>
			</SectionCard>
		{:else if validation}
			{#if validation.success}
				<Alert.Root variant="success">
					<CircleCheck class="size-4" />
					<Alert.Title>Compiles cleanly{validation.system_name ? ` — ${validation.system_name}` : ''}</Alert.Title>
					<Alert.Description>
						<dl class="mt-2 grid grid-cols-2 gap-3">
							<div class="rounded-md border bg-muted/40 p-3">
								<dt class="text-xs text-muted-foreground">Line types</dt>
								<dd class="text-lg tabular-nums">{validation.line_type_count ?? 0}</dd>
							</div>
							<div class="rounded-md border bg-muted/40 p-3">
								<dt class="text-xs text-muted-foreground">Inference rules</dt>
								<dd class="text-lg tabular-nums">{validation.inference_rule_count ?? 0}</dd>
							</div>
						</dl>
					</Alert.Description>
				</Alert.Root>
			{:else}
				<Alert.Root variant="destructive">
					<CircleX class="size-4" />
					<Alert.Title>
						Does not compile ({validation.errors.length}
						{validation.errors.length === 1 ? 'error' : 'errors'})
					</Alert.Title>
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

		{#if outline.length > 0}
			<SectionCard title="Outline">
				<p class="mb-3 text-sm text-muted-foreground">
					How this system's proofs are filed. An imported corpus takes this from the
					section headers its source draws; the number beside a folder is the proofs
					it holds directly. Pick one to read them.
				</p>
				<!-- Two columns only once there is a second thing to put in one: an
				     outline nobody has picked from should have the card's whole width. -->
				<div class={['grid gap-4', selectedFolder && 'md:grid-cols-2']}>
					<OutlineTree
						folders={outline}
						open
						selected={selectedFolder?.id ?? null}
						onselect={(folder) => (selectedFolder = folder)}
					/>
					{#if selectedFolder}
						<FolderProofs systemId={system.id} folder={selectedFolder} />
					{/if}
				</div>
			</SectionCard>
		{/if}

		<SystemParts {system} />

		<EntityFooter id={system.id} createdAt={system.created_at} />
	{/if}
</PageContainer>
