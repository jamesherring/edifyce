<script lang="ts">
	import MockShell from '$lib/mockups/mock-shell.svelte';
	let { children } = $props();
</script>

<MockShell design="1">{@render children()}</MockShell>
