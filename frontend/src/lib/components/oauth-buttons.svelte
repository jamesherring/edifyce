<script lang="ts">
	import { onMount } from 'svelte';
	import type { Component } from 'svelte';
	import { Button } from '$lib/components/ui/button';
	import { api, ApiError } from '$lib/api';
	import Github from '$lib/components/icons/github.svelte';
	import Google from '$lib/components/icons/google.svelte';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';

	// The verb shown before the provider name — "Sign up with" on register,
	// "Continue with" on login.
	let { verb = 'Continue with' }: { verb?: string } = $props();

	// Presentation for the providers we ship icons/labels for. Providers the
	// backend enables but we don't have here still render (see `present`), just
	// with a capitalized name and no icon — so enabling a new provider server-side
	// never silently hides its button.
	const META: Record<string, { name: string; icon: Component }> = {
		google: { name: 'Google', icon: Google },
		github: { name: 'GitHub', icon: Github }
	};

	function present(provider: string): { name: string; icon: Component | null } {
		return META[provider] ?? { name: provider[0].toUpperCase() + provider.slice(1), icon: null };
	}

	let providers = $state<string[]>([]);
	let pending = $state<string | null>(null);
	let error = $state<string | null>(null);

	onMount(async () => {
		try {
			const res = await api.oauthProviders();
			providers = res.providers;
		} catch {
			// No providers endpoint / none configured — render nothing.
			providers = [];
		}
	});

	async function start(provider: string) {
		pending = provider;
		error = null;
		try {
			const { authorization_url } = await api.oauthAuthorizeUrl(provider);
			window.location.href = authorization_url;
		} catch (err) {
			error = err instanceof ApiError ? err.message : String(err);
			pending = null;
		}
	}
</script>

{#if providers.length > 0}
	<div class="flex flex-col gap-3">
		<div class="flex items-center gap-3">
			<span class="bg-border h-px flex-1"></span>
			<span class="text-muted-foreground text-xs">or</span>
			<span class="bg-border h-px flex-1"></span>
		</div>

		{#if error}
			<p class="text-destructive text-xs">{error}</p>
		{/if}

		{#each providers as provider (provider)}
			{@const meta = present(provider)}
			{@const Icon = meta.icon}
			<Button
				variant="outline"
				type="button"
				onclick={() => start(provider)}
				disabled={pending !== null}
			>
				{#if pending === provider}
					<LoaderCircle class="size-4 animate-spin" />
				{:else if Icon}
					<Icon size={16} />
				{/if}
				{verb} {meta.name}
			</Button>
		{/each}
	</div>
{/if}
