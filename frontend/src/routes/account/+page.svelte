<script lang="ts">
	import { goto } from '$app/navigation';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Badge } from '$lib/components/ui/badge';
	import * as Card from '$lib/components/ui/card';
	import * as Alert from '$lib/components/ui/alert';
	import { auth } from '$lib/auth.svelte';
	import { api, ApiError } from '$lib/api';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import CircleCheck from '@lucide/svelte/icons/circle-check-big';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import LogOut from '@lucide/svelte/icons/log-out';

	// Redirect out once we know there is no session.
	$effect(() => {
		if (auth.ready && !auth.user) goto('/login?next=/account');
	});

	let displayName = $state('');
	let profileSaving = $state(false);
	let profileMessage = $state<{ tone: 'ok' | 'error'; text: string } | null>(null);

	// Seed the editable field from the loaded user, once.
	let seeded = $state(false);
	$effect(() => {
		if (auth.user && !seeded) {
			displayName = auth.user.display_name ?? '';
			seeded = true;
		}
	});

	async function saveProfile(event: SubmitEvent) {
		event.preventDefault();
		profileSaving = true;
		profileMessage = null;
		try {
			const updated = await api.updateProfile({
				display_name: displayName.trim() ? displayName.trim() : null
			});
			auth.set(updated);
			profileMessage = { tone: 'ok', text: 'Profile updated.' };
		} catch (err) {
			profileMessage = {
				tone: 'error',
				text: err instanceof ApiError ? err.message : String(err)
			};
		} finally {
			profileSaving = false;
		}
	}

	let newPassword = $state('');
	let confirmPassword = $state('');
	let passwordSaving = $state(false);
	let passwordMessage = $state<{ tone: 'ok' | 'error'; text: string } | null>(null);

	const passwordMismatch = $derived(
		confirmPassword.length > 0 && newPassword !== confirmPassword
	);

	async function savePassword(event: SubmitEvent) {
		event.preventDefault();
		if (newPassword !== confirmPassword) return;
		passwordSaving = true;
		passwordMessage = null;
		try {
			await api.updateProfile({ password: newPassword });
			newPassword = '';
			confirmPassword = '';
			passwordMessage = { tone: 'ok', text: 'Password changed.' };
		} catch (err) {
			passwordMessage = {
				tone: 'error',
				text: err instanceof ApiError ? err.message : String(err)
			};
		} finally {
			passwordSaving = false;
		}
	}

	async function logout() {
		await auth.logout();
		await goto('/');
	}
</script>

<svelte:head><title>Account — Edifyce</title></svelte:head>

{#if auth.user}
	<div class="mx-auto flex max-w-2xl flex-col gap-6">
		<div class="flex flex-col gap-2">
			<h1 class="text-2xl font-bold tracking-tight">Account</h1>
			<p class="text-muted-foreground">Manage your profile and sign-in details.</p>
		</div>

		<Card.Root>
			<Card.Header>
				<Card.Title>Profile</Card.Title>
				<Card.Description>Your email is used to sign in and can't be changed here.</Card.Description>
			</Card.Header>
			<Card.Content>
				<form class="flex flex-col gap-4" onsubmit={saveProfile}>
					{#if profileMessage}
						<Alert.Root variant={profileMessage.tone === 'ok' ? 'default' : 'destructive'}>
							{#if profileMessage.tone === 'ok'}<CircleCheck />{:else}<TriangleAlert />{/if}
							<Alert.Description>{profileMessage.text}</Alert.Description>
						</Alert.Root>
					{/if}

					<div class="flex flex-col gap-2">
						<Label for="email">Email</Label>
						<div class="flex items-center gap-2">
							<Input id="email" type="email" value={auth.user.email} disabled />
							{#if auth.user.is_verified}
								<Badge variant="success">Verified</Badge>
							{:else}
								<Badge variant="outline">Unverified</Badge>
							{/if}
						</div>
					</div>

					<div class="flex flex-col gap-2">
						<Label for="display-name">Display name</Label>
						<Input id="display-name" type="text" placeholder="Your name" bind:value={displayName} />
					</div>

					<div>
						<Button type="submit" disabled={profileSaving}>
							{#if profileSaving}
								<LoaderCircle class="size-4 animate-spin" /> Saving…
							{:else}
								Save profile
							{/if}
						</Button>
					</div>
				</form>
			</Card.Content>
		</Card.Root>

		<Card.Root>
			<Card.Header>
				<Card.Title>Password</Card.Title>
				<Card.Description>Choose a new password for your account.</Card.Description>
			</Card.Header>
			<Card.Content>
				<form class="flex flex-col gap-4" onsubmit={savePassword}>
					{#if passwordMessage}
						<Alert.Root variant={passwordMessage.tone === 'ok' ? 'default' : 'destructive'}>
							{#if passwordMessage.tone === 'ok'}<CircleCheck />{:else}<TriangleAlert />{/if}
							<Alert.Description>{passwordMessage.text}</Alert.Description>
						</Alert.Root>
					{/if}

					<div class="flex flex-col gap-2">
						<Label for="new-password">New password</Label>
						<Input
							id="new-password"
							type="password"
							autocomplete="new-password"
							bind:value={newPassword}
						/>
					</div>

					<div class="flex flex-col gap-2">
						<Label for="confirm-password">Confirm new password</Label>
						<Input
							id="confirm-password"
							type="password"
							autocomplete="new-password"
							bind:value={confirmPassword}
							aria-invalid={passwordMismatch}
						/>
						{#if passwordMismatch}
							<p class="text-destructive text-xs">Passwords do not match.</p>
						{/if}
					</div>

					<div>
						<Button type="submit" disabled={passwordSaving || !newPassword || passwordMismatch}>
							{#if passwordSaving}
								<LoaderCircle class="size-4 animate-spin" /> Saving…
							{:else}
								Change password
							{/if}
						</Button>
					</div>
				</form>
			</Card.Content>
		</Card.Root>

		<Card.Root>
			<Card.Header>
				<Card.Title>Session</Card.Title>
				<Card.Description>Sign out of this device.</Card.Description>
			</Card.Header>
			<Card.Content>
				<Button variant="outline" onclick={logout}>
					<LogOut class="size-4" /> Log out
				</Button>
			</Card.Content>
		</Card.Root>
	</div>
{:else}
	<div class="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm">
		<LoaderCircle class="size-4 animate-spin" /> Loading…
	</div>
{/if}
