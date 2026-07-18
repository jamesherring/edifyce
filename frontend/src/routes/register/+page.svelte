<script lang="ts">
	import { goto } from '$app/navigation';
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
	let displayName = $state('');
	let password = $state('');
	let confirm = $state('');
	let loading = $state(false);
	let error = $state<string | null>(null);

	// Sole navigation authority once signed in — avoids racing submit()'s goto
	// (the effect flush runs last and would override it).
	$effect(() => {
		if (auth.ready && auth.user) goto('/');
	});

	const mismatch = $derived(confirm.length > 0 && password !== confirm);

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (password !== confirm) {
			error = 'Passwords do not match.';
			return;
		}
		loading = true;
		error = null;
		try {
			await auth.register(email, password, displayName);
			// The effect above navigates once auth.user is set.
		} catch (err) {
			if (err instanceof ApiError && err.status === 400) {
				// fastapi-users returns REGISTER_USER_ALREADY_EXISTS as the detail
				// string, or a password-policy { reason } — surface the latter as-is.
				error =
					err.message === 'REGISTER_USER_ALREADY_EXISTS'
						? 'An account with that email already exists.'
						: err.message;
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

<svelte:head><title>Sign up — Edifyce</title></svelte:head>

<div class="mx-auto max-w-md">
	<Card.Root>
		<Card.Header>
			<Card.Title class="text-xl">Create an account</Card.Title>
			<Card.Description>Save the systems and proofs you build on Edifyce.</Card.Description>
		</Card.Header>
		<Card.Content class="flex flex-col gap-4">
			<form class="flex flex-col gap-4" onsubmit={submit}>
				{#if error}
					<Alert.Root variant="destructive">
						<TriangleAlert />
						<Alert.Title>Could not sign up</Alert.Title>
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
					<Label for="display-name">Display name <span class="text-muted-foreground">(optional)</span></Label>
					<Input
						id="display-name"
						type="text"
						autocomplete="nickname"
						placeholder="How you'll appear"
						bind:value={displayName}
					/>
				</div>

				<div class="flex flex-col gap-2">
					<Label for="password">Password</Label>
					<Input
						id="password"
						type="password"
						autocomplete="new-password"
						bind:value={password}
						required
					/>
				</div>

				<div class="flex flex-col gap-2">
					<Label for="confirm">Confirm password</Label>
					<Input
						id="confirm"
						type="password"
						autocomplete="new-password"
						bind:value={confirm}
						required
						aria-invalid={mismatch}
					/>
					{#if mismatch}
						<p class="text-destructive text-xs">Passwords do not match.</p>
					{/if}
				</div>

				<Button type="submit" disabled={loading || !email || !password || mismatch}>
					{#if loading}
						<LoaderCircle class="size-4 animate-spin" /> Creating account…
					{:else}
						Sign up
					{/if}
				</Button>
			</form>

			<OauthButtons verb="Sign up with" />
		</Card.Content>
		<Card.Footer class="text-muted-foreground justify-center text-sm">
			<span>
				Already have an account?
				<a class="text-foreground font-medium underline-offset-4 hover:underline" href="/login">
					Log in
				</a>
			</span>
		</Card.Footer>
	</Card.Root>
</div>
