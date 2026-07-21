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
	import {
		api,
		ApiError,
		type FormalSystemDetail,
		type SystemValidation,
		type SystemSource
	} from '$lib/api';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import CircleCheck from '@lucide/svelte/icons/circle-check-big';
	import CircleX from '@lucide/svelte/icons/circle-x';
	import Code from '@lucide/svelte/icons/code';

	let system = $state<FormalSystemDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let validation = $state<SystemValidation | null>(null);
	let validating = $state(false);

	let source = $state<SystemSource | null>(null);
	let sourceOpen = $state(false);
	let sourceLoading = $state(false);
	let sourceError = $state<string | null>(null);

	async function load(id: string) {
		loading = true;
		error = null;
		validation = null;
		source = null;
		sourceOpen = false;
		try {
			system = await api.systems.get(id);
		} catch (err) {
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
		loading = false;
		runValidation(id);
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

	async function toggleSource() {
		sourceOpen = !sourceOpen;
		if (sourceOpen && source === null && system) {
			sourceLoading = true;
			sourceError = null;
			try {
				source = await api.systems.source(system.id);
			} catch (err) {
				sourceError = err instanceof ApiError ? err.message : String(err);
			} finally {
				sourceLoading = false;
			}
		}
	}

	// Re-load whenever the route id changes.
	$effect(() => {
		const id = page.params.id;
		if (id) load(id);
	});
</script>

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

		<SystemParts {system} />

		<!-- The lowered .edi source, fetched lazily. -->
		<div>
			<Button variant="outline" size="sm" onclick={toggleSource}>
				<Code class="size-4" />
				{sourceOpen ? 'Hide source' : 'View source'}
			</Button>
			{#if sourceOpen}
				<div class="mt-3">
					{#if sourceLoading}
						<LoadingSpinner message="Lowering source…" />
					{:else if sourceError}
						<Alert.Root variant="destructive">
							<TriangleAlert class="size-4" />
							<Alert.Description>{sourceError}</Alert.Description>
						</Alert.Root>
					{:else if source}
						<pre class="overflow-x-auto rounded-md border bg-muted/30 p-4 font-mono text-xs leading-relaxed">{source.source}</pre>
					{/if}
				</div>
			{/if}
		</div>

		<EntityFooter id={system.id} createdAt={system.created_at} />
	{/if}
</PageContainer>
