<script lang="ts">
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
	import { api, ApiError } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import { toastSuccess, toastError } from '$lib/toast';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';

	let name = $state('');
	let description = $state('');
	let saving = $state(false);
	let error = $state<string | null>(null);

	// Creating requires an account; bounce to login and come back.
	$effect(() => {
		if (auth.ready && !auth.user) goto('/login?next=/systems/new');
	});

	async function create(event: SubmitEvent) {
		event.preventDefault();
		if (!name.trim() || saving) return;
		saving = true;
		error = null;
		try {
			const created = await api.systems.create({
				name: name.trim(),
				description: description.trim() || null
			});
			toastSuccess('System created.');
			goto(`/systems/${created.id}/edit`);
		} catch (err) {
			error = err instanceof ApiError ? err.message : String(err);
			toastError('Could not create system.');
			saving = false;
		}
	}
</script>

<svelte:head><title>New formal system — Edifyce</title></svelte:head>

<PageContainer maxWidth="2xl" gap>
	<BackLink href="/systems" label="All systems" />
	<PageHeader title="New formal system" description="Start with a name; add notation, rules and definitions next." />

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
					<Label for="name">Name</Label>
					<Input id="name" bind:value={name} placeholder="e.g. Propositional Logic" maxlength={256} required />
				</div>
				<div class="flex flex-col gap-2">
					<Label for="description">Description <span class="text-muted-foreground">(optional)</span></Label>
					<Textarea id="description" bind:value={description} rows={3} placeholder="What is this system for?" />
				</div>
				<div class="flex justify-end gap-2">
					<Button type="button" variant="ghost" href="/systems">Cancel</Button>
					<Button type="submit" disabled={saving || name.trim().length === 0}>
						{#if saving}
							<LoaderCircle class="size-4 animate-spin" /> Creating…
						{:else}
							Create system
						{/if}
					</Button>
				</div>
			</form>
		</Card.Content>
	</Card.Root>
</PageContainer>
