<script lang="ts">
	import MockShell from '$lib/mockups/mock-shell.svelte';
	let { children } = $props();
</script>

<MockShell design="6">{@render children()}</MockShell>
