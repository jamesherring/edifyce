<script lang="ts">
	import * as Table from '$lib/components/ui/table';
	import { Badge } from '$lib/components/ui/badge';
	import SectionCard from '$lib/components/SectionCard.svelte';
	import InlineEmpty from '$lib/components/InlineEmpty.svelte';
	import type { Binding, FormalSystemDetail } from '$lib/api';

	let { system }: { system: FormalSystemDetail } = $props();

	function bindingsText(bindings: Binding[]): string {
		return bindings.map((b) => `${b.var} : ${b.sort}`).join(', ');
	}

	const isEmpty = $derived(
		system.brackets.length === 0 &&
			system.sorts.length === 0 &&
			system.productions.length === 0 &&
			system.lines.length === 0 &&
			system.definitions.length === 0 &&
			system.axioms.length === 0 &&
			system.rules.length === 0
	);
</script>

{#if isEmpty}
	<SectionCard variant="muted">
		<InlineEmpty message="This system has no notation, rules, or definitions yet." centered />
	</SectionCard>
{:else}
	<div class="space-y-4">
		{#if system.sorts.length > 0}
			<SectionCard title="Sorts">
				<div class="flex flex-wrap gap-1.5">
					{#each system.sorts as sort (sort.id)}
						<Badge variant="outline" class="font-mono">{sort.name}</Badge>
					{/each}
				</div>
			</SectionCard>
		{/if}

		{#if system.brackets.length > 0}
			<SectionCard title="Brackets">
				<div class="flex flex-wrap gap-3 font-mono text-sm">
					{#each system.brackets as pair (pair.id)}
						<span class="rounded border bg-muted/40 px-2 py-1">{pair.opening} {pair.closing}</span>
					{/each}
				</div>
			</SectionCard>
		{/if}

		{#if system.productions.length > 0}
			<SectionCard title="Grammar">
				<Table.Root>
					<Table.Header>
						<Table.Row>
							<Table.Head>Name</Table.Head>
							<Table.Head>Sort</Table.Head>
							<Table.Head>Rule</Table.Head>
							<Table.Head class="hidden sm:table-cell">Where</Table.Head>
						</Table.Row>
					</Table.Header>
					<Table.Body>
						{#each system.productions as prod (prod.id)}
							<Table.Row>
								<Table.Cell class="font-medium">{prod.name}</Table.Cell>
								<Table.Cell class="font-mono text-muted-foreground">{prod.sort}</Table.Cell>
								<Table.Cell class="font-mono">
									{#if prod.template}{prod.template}{:else if prod.regex}<span
											class="text-muted-foreground">matches</span
										> {prod.regex}{/if}
								</Table.Cell>
								<Table.Cell class="hidden font-mono text-xs text-muted-foreground sm:table-cell">
									{bindingsText(prod.bindings)}
								</Table.Cell>
							</Table.Row>
						{/each}
					</Table.Body>
				</Table.Root>
			</SectionCard>
		{/if}

		{#if system.lines.length > 0}
			<SectionCard title={system.lines.length > 1 ? 'Line types' : 'Line type'}>
				<div class="space-y-4">
					{#each system.lines as line (line.id)}
						<div class="space-y-1 text-sm">
							<div class="flex flex-wrap items-baseline gap-2">
								<span class="font-medium">{line.name}</span>
								<span class="font-mono text-muted-foreground">{line.shape}</span>
								{#if line.logical_sort}
									<span class="text-xs text-muted-foreground"
										>logical: <span class="font-mono">{line.logical_sort}</span></span
									>
								{/if}
							</div>
							{#if line.parts.length > 0}
								<div class="font-mono text-xs text-muted-foreground">
									{#each line.parts as part (part.id)}
										<span class="mr-3">{part.name} matches {part.regex}</span>
									{/each}
								</div>
							{/if}
						</div>
					{/each}
				</div>
			</SectionCard>
		{/if}

		{#if system.axioms.length > 0}
			<SectionCard title="Axioms">
				<Table.Root>
					<Table.Header>
						<Table.Row>
							<Table.Head>Label</Table.Head>
							<Table.Head>Name</Table.Head>
							<Table.Head>Formula</Table.Head>
							<Table.Head class="hidden sm:table-cell">Where</Table.Head>
						</Table.Row>
					</Table.Header>
					<Table.Body>
						{#each system.axioms as axiom (axiom.id)}
							<Table.Row>
								<Table.Cell class="font-mono">{axiom.label}</Table.Cell>
								<Table.Cell class="font-medium">{axiom.name}</Table.Cell>
								<Table.Cell class="font-mono">{axiom.formula}</Table.Cell>
								<Table.Cell class="hidden font-mono text-xs text-muted-foreground sm:table-cell">
									{bindingsText(axiom.bindings)}
								</Table.Cell>
							</Table.Row>
						{/each}
					</Table.Body>
				</Table.Root>
			</SectionCard>
		{/if}

		{#if system.rules.length > 0}
			<SectionCard title="Inference rules">
				<Table.Root>
					<Table.Header>
						<Table.Row>
							<Table.Head>Label</Table.Head>
							<Table.Head>Name</Table.Head>
							<Table.Head>From</Table.Head>
							<Table.Head>Infer</Table.Head>
							<Table.Head class="hidden sm:table-cell">Where</Table.Head>
						</Table.Row>
					</Table.Header>
					<Table.Body>
						{#each system.rules as rule (rule.id)}
							<Table.Row>
								<Table.Cell class="font-mono">{rule.label}</Table.Cell>
								<Table.Cell class="font-medium">
									{rule.name}
									{#if rule.matching === 'string'}
										<Badge variant="secondary" class="ml-2 align-middle text-xs font-normal">
											string rewriting
										</Badge>
									{/if}
								</Table.Cell>
								<Table.Cell class="font-mono text-muted-foreground">
									{rule.antecedents.join(' ; ') || '—'}
								</Table.Cell>
								<Table.Cell class="font-mono">{rule.deduction}</Table.Cell>
								<Table.Cell class="hidden font-mono text-xs text-muted-foreground sm:table-cell">
									{#if rule.side_conditions.length > 0}
										<div>{rule.side_conditions.join(' ; ')}</div>
									{/if}
									{#if rule.bindings.length > 0}
										<div class="opacity-70">{bindingsText(rule.bindings)}</div>
									{/if}
									{#if rule.side_conditions.length === 0 && rule.bindings.length === 0}
										—
									{/if}
								</Table.Cell>
							</Table.Row>
						{/each}
					</Table.Body>
				</Table.Root>
			</SectionCard>
		{/if}

		{#if system.definitions.length > 0}
			<SectionCard title="Definitions">
				<Table.Root>
					<Table.Header>
						<Table.Row>
							<Table.Head>Name</Table.Head>
							<Table.Head>Defines</Table.Head>
							<Table.Head>As</Table.Head>
							<Table.Head class="hidden sm:table-cell">When</Table.Head>
						</Table.Row>
					</Table.Header>
					<Table.Body>
						{#each system.definitions as def (def.id)}
							<Table.Row>
								<Table.Cell class="font-medium">
									<a class="underline" href={`/systems/${system.id}/definitions/${def.id}`}>{def.name}</a>
								</Table.Cell>
								<Table.Cell class="font-mono">{def.higher}</Table.Cell>
								<Table.Cell class="font-mono">{def.lower}</Table.Cell>
								<Table.Cell class="hidden font-mono text-xs text-muted-foreground sm:table-cell">
									{#if def.provisos.length > 0}
										<div>{def.provisos.join(' ; ')}</div>
									{/if}
									{#if def.fresh.length > 0}
										<div class="opacity-70">fresh {bindingsText(def.fresh)}</div>
									{/if}
									{#if def.bindings.length > 0}
										<div class="opacity-70">{bindingsText(def.bindings)}</div>
									{/if}
									{#if def.provisos.length === 0 && def.fresh.length === 0 && def.bindings.length === 0}
										—
									{/if}
								</Table.Cell>
							</Table.Row>
						{/each}
					</Table.Body>
				</Table.Root>
			</SectionCard>
		{/if}
	</div>
{/if}
