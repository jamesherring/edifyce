<script lang="ts">
	import { onMount } from 'svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { api } from '$lib/api';

	let state = $state<'checking' | 'online' | 'offline'>('checking');

	async function check() {
		state = 'checking';
		try {
			const res = await api.health();
			state = res.status === 'ok' ? 'online' : 'offline';
		} catch {
			state = 'offline';
		}
	}

	onMount(() => {
		check();
	});
</script>

<button onclick={check} title="Backend status — click to re-check" class="cursor-pointer">
	{#if state === 'online'}
		<Badge variant="success">
			<span class="size-1.5 rounded-full bg-current"></span> Backend online
		</Badge>
	{:else if state === 'offline'}
		<Badge variant="destructive">
			<span class="size-1.5 rounded-full bg-current"></span> Backend offline
		</Badge>
	{:else}
		<Badge variant="secondary">
			<span class="size-1.5 animate-pulse rounded-full bg-current"></span> Checking…
		</Badge>
	{/if}
</button>
