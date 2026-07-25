<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Button } from '$lib/components/ui/button';
	import { theme } from '$lib/theme.svelte';
	import { auth } from '$lib/auth.svelte';
	import Sun from '@lucide/svelte/icons/sun';
	import Moon from '@lucide/svelte/icons/moon';
	import UserRound from '@lucide/svelte/icons/user-round';
	import LogOut from '@lucide/svelte/icons/log-out';
	import Turnstile from '$lib/components/icons/turnstile.svelte';

	const nav = [
		{ href: '/', label: 'Home' },
		{ href: '/systems', label: 'Systems' },
		{ href: '/proofs', label: 'Proofs' }
	];

	function isActive(href: string) {
		return href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
	}

	async function logout() {
		await auth.logout();
		await goto('/');
	}
</script>

<header
	class="bg-background/80 sticky top-0 z-40 w-full border-b backdrop-blur supports-[backdrop-filter]:bg-background/60"
>
	<div class="mx-auto flex h-14 max-w-5xl items-center gap-2 px-4 sm:gap-4">
		<a href="/" class="flex shrink-0 items-center gap-2 py-2 font-semibold">
			<span class="bg-primary text-primary-foreground grid size-7 place-items-center rounded-md">
				<Turnstile class="size-4" />
			</span>
			<!-- The mark alone carries the branding on a phone; the wordmark is the
			     first thing to go when the row can't fit. -->
			<span class="hidden tracking-tight sm:inline">Edifyce</span>
		</a>

		<!-- flex-1 + min-w-0 so the nav, not the page, absorbs a narrow viewport:
		     it scrolls itself rather than pushing the controls off-screen. -->
		<nav class="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto sm:ml-2">
			{#each nav as item (item.href)}
				<a
					href={item.href}
					class={[
						'shrink-0 rounded-md px-2 py-2 text-sm font-medium transition-colors sm:px-3',
						isActive(item.href)
							? 'bg-accent text-accent-foreground'
							: 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
					]}
				>
					{item.label}
				</a>
			{/each}
		</nav>

		<div class="flex shrink-0 items-center gap-1 sm:gap-2">
			{#if auth.ready}
				{#if auth.user}
					<a
						href="/account"
						class={[
							'flex items-center gap-1.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors sm:px-3',
							isActive('/account')
								? 'bg-accent text-accent-foreground'
								: 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
						]}
						title="Account"
					>
						<UserRound class="size-4" />
						<span class="hidden max-w-[12rem] truncate sm:inline">
							{auth.user.display_name || auth.user.email}
						</span>
					</a>
					<Button variant="ghost" size="icon" onclick={logout} title="Log out">
						<LogOut class="size-4" />
					</Button>
				{:else}
					<Button href="/login" variant="ghost" size="sm">Log in</Button>
					<Button href="/register" size="sm">Sign up</Button>
				{/if}
			{/if}

			<Button variant="ghost" size="icon" onclick={() => theme.toggle()} title="Toggle theme">
				{#if theme.value === 'dark'}
					<Sun class="size-4" />
				{:else}
					<Moon class="size-4" />
				{/if}
			</Button>
		</div>
	</div>
</header>
