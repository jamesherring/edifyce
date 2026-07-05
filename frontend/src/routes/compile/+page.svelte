<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import * as Alert from '$lib/components/ui/alert';
	import { Label } from '$lib/components/ui/label';
	import CodeEditor from '$lib/components/code-editor.svelte';
	import { api, ApiError, type CompileResponse } from '$lib/api';
	import { EXAMPLE_SYSTEM } from '$lib/examples';
	import Play from '@lucide/svelte/icons/play';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import CircleCheck from '@lucide/svelte/icons/circle-check-big';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';

	let code = $state(EXAMPLE_SYSTEM);
	let loading = $state(false);
	let result = $state<CompileResponse | null>(null);
	let requestError = $state<string | null>(null);

	async function compile() {
		loading = true;
		result = null;
		requestError = null;
		try {
			result = await api.compile(code);
		} catch (err) {
			requestError = err instanceof ApiError ? err.message : String(err);
		} finally {
			loading = false;
		}
	}

	function reset() {
		code = EXAMPLE_SYSTEM;
		result = null;
		requestError = null;
	}
</script>

<div class="flex flex-col gap-2">
	<h1 class="text-2xl font-bold tracking-tight">Compile a formal system</h1>
	<p class="text-muted-foreground">
		Write Edifyce source describing your line types and inference rules, then compile it to check the
		structure. Sends <code class="text-foreground">POST /formal-systems/compile</code>.
	</p>
</div>

<div class="mt-6 grid gap-6 lg:grid-cols-2">
	<Card.Root>
		<Card.Header>
			<div class="flex items-center justify-between">
				<Card.Title>System source</Card.Title>
				<Button variant="ghost" size="sm" onclick={reset}>
					<RotateCcw class="size-3.5" /> Reset
				</Button>
			</div>
			<Card.Description>Indentation is significant (4 spaces per level).</Card.Description>
		</Card.Header>
		<Card.Content class="flex flex-col gap-4">
			<div class="flex flex-col gap-2">
				<Label for="system-code">Code</Label>
				<CodeEditor id="system-code" bind:value={code} rows={16} />
			</div>
			<Button onclick={compile} disabled={loading || code.trim().length === 0}>
				{#if loading}
					<LoaderCircle class="size-4 animate-spin" /> Compiling…
				{:else}
					<Play class="size-4" /> Compile
				{/if}
			</Button>
		</Card.Content>
	</Card.Root>

	<Card.Root>
		<Card.Header>
			<Card.Title>Result</Card.Title>
			<Card.Description>Structure metadata or the errors that stopped compilation.</Card.Description>
		</Card.Header>
		<Card.Content class="flex flex-col gap-4">
			{#if requestError}
				<Alert.Root variant="destructive">
					<TriangleAlert />
					<Alert.Title>Request failed</Alert.Title>
					<Alert.Description>
						<span class="whitespace-pre-wrap">{requestError}</span>
					</Alert.Description>
				</Alert.Root>
			{:else if result === null}
				<p class="text-muted-foreground py-8 text-center text-sm">
					Compile a system to see its structure here.
				</p>
			{:else if result.success}
				<Alert.Root variant="success">
					<CircleCheck />
					<Alert.Title>Compiled successfully</Alert.Title>
					<Alert.Description>
						{#if result.system_name}
							Formal system <strong>{result.system_name}</strong> is well-formed.
						{:else}
							The source compiled to an empty, unnamed system.
						{/if}
					</Alert.Description>
				</Alert.Root>

				<dl class="grid grid-cols-2 gap-3">
					<div class="bg-muted/40 rounded-lg border p-4">
						<dt class="text-muted-foreground text-xs font-medium uppercase tracking-wide">
							Line types
						</dt>
						<dd class="mt-1 text-2xl font-semibold tabular-nums">
							{result.line_type_count ?? 0}
						</dd>
					</div>
					<div class="bg-muted/40 rounded-lg border p-4">
						<dt class="text-muted-foreground text-xs font-medium uppercase tracking-wide">
							Inference rules
						</dt>
						<dd class="mt-1 text-2xl font-semibold tabular-nums">
							{result.inference_rule_count ?? 0}
						</dd>
					</div>
				</dl>
			{:else}
				<Alert.Root variant="destructive">
					<TriangleAlert />
					<Alert.Title>
						{result.errors.length} compilation {result.errors.length === 1 ? 'error' : 'errors'}
					</Alert.Title>
					<Alert.Description>Fix the lines below and compile again.</Alert.Description>
				</Alert.Root>
				<ul class="flex flex-col gap-2">
					{#each result.errors as error, i (i)}
						<li
							class="border-destructive/30 bg-destructive/5 text-destructive rounded-md border px-3 py-2 font-mono text-sm"
						>
							{error}
						</li>
					{/each}
				</ul>
			{/if}
		</Card.Content>
	</Card.Root>
</div>
