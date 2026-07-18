<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import * as Card from '$lib/components/ui/card';
	import * as Alert from '$lib/components/ui/alert';
	import OauthButtons from '$lib/components/oauth-buttons.svelte';
	import { auth } from '$lib/auth.svelte';
	import { ApiError } from '$lib/api';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';

	let email = $state('');
	let password = $state('');
	let loading = $state(false);
	let error = $state<string | null>(null);

	// Once signed in — whether on arrival or right after logging in — leave for
	// the requested `next` target (or home). Keeping this the sole navigation
	// avoids a race with a second goto in submit(): the effect flush runs last
	// and would otherwise override the intended destination.
	$effect(() => {
		if (auth.ready && auth.user) {
			const next = page.url.searchParams.get('next');
			goto(next && next.startsWith('/') ? next : '/');
		}
	});

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		loading = true;
		error = null;
		try {
			await auth.login(email, password);
			// The effect above navigates once auth.user is set.
		} catch (err) {
			if (err instanceof ApiError && err.status === 400) {
				error = 'Incorrect email or password.';
			} else if (err instanceof ApiError) {
				error = err.message;
			} else {
				error = String(err);
			}
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head><title>Log in — Edifyce</title></svelte:head>

<div class="mx-auto max-w-md">
	<Card.Root>
		<Card.Header>
			<Card.Title class="text-xl">Log in</Card.Title>
			<Card.Description>Welcome back. Enter your details to continue.</Card.Description>
		</Card.Header>
		<Card.Content class="flex flex-col gap-4">
			<form class="flex flex-col gap-4" onsubmit={submit}>
				{#if error}
					<Alert.Root variant="destructive">
						<TriangleAlert />
						<Alert.Title>Could not log in</Alert.Title>
						<Alert.Description>{error}</Alert.Description>
					</Alert.Root>
				{/if}

				<div class="flex flex-col gap-2">
					<Label for="email">Email</Label>
					<Input
						id="email"
						type="email"
						autocomplete="email"
						placeholder="you@example.com"
						bind:value={email}
						required
					/>
				</div>

				<div class="flex flex-col gap-2">
					<Label for="password">Password</Label>
					<Input
						id="password"
						type="password"
						autocomplete="current-password"
						bind:value={password}
						required
					/>
				</div>

				<Button type="submit" disabled={loading || !email || !password}>
					{#if loading}
						<LoaderCircle class="size-4 animate-spin" /> Logging in…
					{:else}
						Log in
					{/if}
				</Button>
			</form>

			<OauthButtons verb="Continue with" />
		</Card.Content>
		<Card.Footer class="text-muted-foreground justify-center text-sm">
			<span>
				No account?
				<a class="text-foreground font-medium underline-offset-4 hover:underline" href="/register">
					Sign up
				</a>
			</span>
		</Card.Footer>
	</Card.Root>
</div>
