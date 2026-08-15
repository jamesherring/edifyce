<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import * as Card from '$lib/components/ui/card';
	import BookOpen from '@lucide/svelte/icons/book-open';
	import CircleCheck from '@lucide/svelte/icons/circle-check-big';
	import Code from '@lucide/svelte/icons/code';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';

	const features = [
		{
			icon: BookOpen,
			title: 'Human Readable',
			body: 'Definitions correspond to familiar notation, so proofs read the way mathematicians write them.'
		},
		{
			icon: CircleCheck,
			title: 'Computer Verifiable',
			body: 'Every proof lives inside a formal system whose inference rules are encoded and mechanically checked.'
		},
		{
			icon: Code,
			title: 'Composable',
			body: 'Proofs can reference earlier results, so higher-level mathematics builds on what came before.'
		}
	];
</script>

<section class="flex flex-col items-center gap-6 py-12 text-center">
	<h1 class="max-w-3xl text-4xl font-bold tracking-tight sm:text-5xl">
		Human-Readable,<br />Computer-Verifiable Mathematics
	</h1>
	<p class="text-muted-foreground max-w-xl text-lg">
		Edifyce is a tool for the digitisation of mathematics — building a verified library of
		definitions and proofs that are readable by both humans and computers.
	</p>
	<div class="flex flex-wrap items-center justify-center gap-3">
		<Button href="/systems">
			Browse systems <ArrowRight class="size-4" />
		</Button>
		<Button href="/systems/new" variant="outline">Create a system</Button>
	</div>
</section>

<section class="grid gap-4 py-8 sm:grid-cols-3">
	{#each features as feature (feature.title)}
		{@const Icon = feature.icon}
		<Card.Root>
			<Card.Header>
				<span class="bg-primary/10 text-primary grid size-9 place-items-center rounded-md">
					<Icon class="size-5" />
				</span>
				<Card.Title class="pt-2">{feature.title}</Card.Title>
			</Card.Header>
			<Card.Content>
				<p class="text-muted-foreground text-sm">{feature.body}</p>
			</Card.Content>
		</Card.Root>
	{/each}
</section>

<section class="py-8">
	<Card.Root class="bg-muted">
		<Card.Header>
			<Card.Title>How it works</Card.Title>
			<Card.Description>Define a system, then prove in it.</Card.Description>
		</Card.Header>
		<Card.Content class="grid gap-4 sm:grid-cols-2">
			<div class="flex gap-3">
				<span
					class="bg-primary text-primary-foreground grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold"
					>1</span
				>
				<div>
					<p class="font-medium">Define a formal system</p>
					<p class="text-muted-foreground text-sm">
						Give it notation, line types and inference rules. Edifyce checks that it compiles and
						publishes it to the shared library when you’re ready.
					</p>
				</div>
			</div>
			<div class="flex gap-3">
				<span
					class="bg-primary text-primary-foreground grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold"
					>2</span
				>
				<div>
					<p class="font-medium">Verify a proof</p>
					<p class="text-muted-foreground text-sm">
						Write a proof against any system and have each line mechanically checked, with
						line-level diagnostics.
					</p>
				</div>
			</div>
		</Card.Content>
	</Card.Root>
</section>
