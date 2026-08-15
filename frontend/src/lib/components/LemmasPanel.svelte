<script lang="ts">
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import * as Card from '$lib/components/ui/card';
	import { Combobox, type ComboboxOption } from '$lib/components/ui/combobox';
	import {
		api,
		ApiError,
		type ProofDetail,
		type ProofSummary,
		type ProofReferenceInput
	} from '$lib/api';
	import { toastSuccess, toastError } from '$lib/toast';
	import LoaderCircle from '@lucide/svelte/icons/loader-circle';
	import Plus from '@lucide/svelte/icons/plus';
	import Trash2 from '@lucide/svelte/icons/trash-2';

	let {
		proof,
		onUpdated
	}: {
		proof: ProofDetail;
		/** Called with the fresh detail after references are saved, so the parent
		 * can reflect the cleared verdict a reference change causes. */
		onUpdated?: (updated: ProofDetail) => void;
	} = $props();

	// One editable reference row. `name` is display-only, resolved from the
	// candidate list (or the reference itself for already-saved edges).
	interface Row {
		referenced_proof_id: string;
		alias: string;
		name: string;
	}

	let rows = $state<Row[]>([]);
	let candidates = $state<ProofSummary[]>([]);
	let pickValue = $state<string | null>(null);
	let saving = $state(false);
	let error = $state<string | null>(null);

	// Reset the editable rows from the proof whenever it changes identity (a fresh
	// load or a save that returned new references).
	let seededFor = $state<string | null>(null);
	$effect(() => {
		const key = `${proof.id}:${proof.references.map((r) => `${r.referenced_proof_id}/${r.alias}`).join(',')}`;
		if (seededFor === key) return;
		seededFor = key;
		rows = proof.references.map((r) => ({
			referenced_proof_id: r.referenced_proof_id,
			alias: r.alias,
			name: r.name
		}));
		error = null;
	});

	// Candidate lemmas: the owner's other proofs in the same system. (Cross-owner
	// published references aren't creatable through the API yet, so listing the
	// owner's own proofs is the reachable candidate set.) The list endpoint caps a
	// page at 100, so walk the pages — a system with >100 proofs would otherwise
	// leave later lemmas unreachable, since the picker filters the loaded set
	// client-side.
	$effect(() => {
		const systemId = proof.formal_system_id;
		let cancelled = false;
		loadAllCandidates(systemId)
			.then((items) => {
				if (!cancelled) candidates = items;
			})
			.catch(() => {
				if (!cancelled) candidates = [];
			});
		return () => {
			cancelled = true;
		};
	});

	const PAGE = 100;
	async function loadAllCandidates(systemId: string): Promise<ProofSummary[]> {
		const items: ProofSummary[] = [];
		for (let offset = 0; ; offset += PAGE) {
			const page = await api.proofs.list(systemId, { limit: PAGE, offset });
			items.push(...page.items);
			// Stop once this system is exhausted: a short page, or we've reached the
			// reported total (guards against an off-by-one extra request).
			if (page.items.length < PAGE || items.length >= page.total) break;
		}
		return items;
	}

	// A `[alias.line]` citation only parses if the *reference field* of the line
	// type it's written on admits a `.`. The reference field is the first
	// part-named placeholder in the line's shape (mirroring the engine's
	// `_line_layout`) — not just any part, since a second permissive field
	// (e.g. a free-text note) would otherwise mask a restrictive reference field.
	// Fetch the system and, across the line types that have a reference field,
	// warn only when none of them accept a dotted token; otherwise the failure
	// surfaces as an opaque parse error at verify time. `null` = unknown (not yet
	// loaded / no reference field / regex not JS-compatible) and shows no warning.
	let citationDotOk = $state<boolean | null>(null);
	$effect(() => {
		const systemId = proof.formal_system_id;
		let cancelled = false;
		citationDotOk = null;
		api.systems
			.get(systemId)
			.then((system) => {
				if (cancelled) return;
				let anyTested = false;
				for (const line of system.lines) {
					// Commentary carries no citation at all, and its part is typically
					// free text that would full-match `a.1` — treating it as a reference
					// field would mask a restrictive one on the real logical line, the
					// same masking the note above guards against within a line.
					if (line.behaviour === 'comment') continue;
					const regex = referenceFieldRegex(line);
					if (regex === null) continue; // this line type carries no citation field
					try {
						// Full-match: does the reference field accept a whole dotted token?
						if (new RegExp(`^(?:${regex})$`).test('a.1')) {
							citationDotOk = true;
							return;
						}
						anyTested = true;
					} catch {
						// Python-only regex JS can't compile — leave this line untested.
					}
				}
				// Assert "not supported" only when a reference field was actually tested.
				citationDotOk = anyTested ? false : null;
			})
			.catch(() => {
				if (!cancelled) citationDotOk = null;
			});
		return () => {
			cancelled = true;
		};
	});

	// The regex of a line type's reference field: the first placeholder in its
	// shape whose name is one of its parts (the engine's citation slot), or null
	// if the line has no such field.
	function referenceFieldRegex(line: { shape: string; parts: { name: string; regex: string }[] }): string | null {
		const partByName = new Map(line.parts.map((p) => [p.name, p.regex]));
		for (const match of line.shape.matchAll(/<([^>]+)>/g)) {
			const regex = partByName.get(match[1]);
			if (regex !== undefined) return regex;
		}
		return null;
	}

	const referencedIds = $derived(new Set(rows.map((r) => r.referenced_proof_id)));

	// Selectable options: same-system proofs, excluding this proof and ones
	// already referenced. A cyclic pick is still rejected server-side on save.
	const options = $derived<ComboboxOption[]>(
		candidates
			.filter((c) => c.id !== proof.id && !referencedIds.has(c.id))
			.map((c) => ({
				value: c.id,
				label: c.name,
				hint: c.published_at ? 'published' : 'draft',
				keywords: c.slug
			}))
	);

	// A default alias from the proof's slug, sanitised to the allowed shape
	// (`^[A-Za-z][A-Za-z0-9_-]*$`) and kept unique against the current rows.
	function suggestAlias(candidate: ProofSummary): string {
		let base = candidate.slug.replace(/[^A-Za-z0-9_-]/g, '-').replace(/^[^A-Za-z]+/, '');
		if (!base) base = 'lemma';
		const taken = new Set(rows.map((r) => r.alias));
		if (!taken.has(base)) return base;
		for (let i = 2; ; i++) {
			const next = `${base}-${i}`;
			if (!taken.has(next)) return next;
		}
	}

	function addPicked(id: string) {
		const candidate = candidates.find((c) => c.id === id);
		if (!candidate) return;
		rows = [
			...rows,
			{ referenced_proof_id: id, alias: suggestAlias(candidate), name: candidate.name }
		];
		pickValue = null;
	}

	function removeRow(index: number) {
		rows = rows.filter((_, i) => i !== index);
	}

	const dirty = $derived(
		JSON.stringify(rows.map((r) => [r.referenced_proof_id, r.alias])) !==
			JSON.stringify(proof.references.map((r) => [r.referenced_proof_id, r.alias]))
	);

	const aliasPattern = /^[A-Za-z][A-Za-z0-9_-]*$/;
	const validAliases = $derived(
		rows.every((r) => aliasPattern.test(r.alias)) &&
			new Set(rows.map((r) => r.alias)).size === rows.length
	);

	async function save() {
		if (saving || !dirty || !validAliases) return;
		const id = proof.id;
		saving = true;
		error = null;
		const payload: ProofReferenceInput[] = rows.map((r) => ({
			referenced_proof_id: r.referenced_proof_id,
			alias: r.alias
		}));
		try {
			const updated = await api.proofs.setReferences(id, payload);
			onUpdated?.(updated);
			toastSuccess('References saved.');
		} catch (err) {
			error = err instanceof ApiError ? err.message : String(err);
			toastError(error);
		} finally {
			saving = false;
		}
	}
</script>

<Card.Root>
	<Card.Header>
		<Card.Title>Lemmas</Card.Title>
		<Card.Description>
			Reference other proofs in this system as lemmas, then cite an imported line
			from your source as <code class="rounded bg-muted px-1 py-0.5 text-xs">[alias.line]</code>
			(e.g. <code class="rounded bg-muted px-1 py-0.5 text-xs">[MP, alias.1, 2]</code>).
		</Card.Description>
	</Card.Header>
	<Card.Content class="flex flex-col gap-4">
		{#if rows.length > 0 && citationDotOk === false}
			<p class="rounded-md border border-warning/40 bg-warning/10 p-2 text-xs text-warning">
				This system's line reference field doesn't appear to allow <code>.</code>, so a
				<code>[alias.line]</code> citation won't parse. Widen the reference part's pattern to
				include <code>.</code> in the system editor before citing an imported line.
			</p>
		{/if}

		{#if rows.length === 0}
			<p class="text-sm text-muted-foreground">No lemmas referenced yet.</p>
		{:else}
			<ul class="flex flex-col gap-2">
				{#each rows as row, i (row.referenced_proof_id)}
					<li class="flex items-end gap-2 rounded-md border p-2">
						<div class="min-w-0 flex-1">
							<div class="truncate text-sm font-medium">{row.name}</div>
							<div class="text-xs text-muted-foreground">
								cite as <code class="rounded bg-muted px-1 py-0.5">[{row.alias || '…'}.line]</code>
							</div>
						</div>
						<div class="flex flex-col gap-1">
							<Label class="text-xs" for={`alias-${i}`}>Alias</Label>
							<Input
								id={`alias-${i}`}
								class="h-8 w-32"
								bind:value={row.alias}
								maxlength={64}
								aria-invalid={!aliasPattern.test(row.alias)}
							/>
						</div>
						<Button
							variant="ghost"
							size="icon"
							class="text-muted-foreground"
							onclick={() => removeRow(i)}
							aria-label={`Remove ${row.name}`}
						>
							<Trash2 class="size-4" />
						</Button>
					</li>
				{/each}
			</ul>
		{/if}

		{#if !validAliases}
			<p class="text-xs text-destructive">
				Each alias must start with a letter, use only letters, digits, <code>-</code> or
				<code>_</code>, and be unique.
			</p>
		{/if}

		<div class="flex items-center gap-2">
			<Combobox
				{options}
				bind:value={pickValue}
				onSelect={addPicked}
				placeholder="Add a lemma…"
				ariaLabel="Add a lemma to cite"
				searchPlaceholder="Search proofs…"
				emptyText="No other proofs in this system."
				disabled={options.length === 0}
				class="flex-1"
			/>
			<Plus class="size-4 text-muted-foreground" />
		</div>

		{#if error}
			<p class="text-sm text-destructive">{error}</p>
		{/if}

		<div class="flex justify-end">
			<Button onclick={save} disabled={!dirty || !validAliases || saving}>
				{#if saving}
					<LoaderCircle class="size-4 animate-spin" /> Saving…
				{:else}
					Save references
				{/if}
			</Button>
		</div>
	</Card.Content>
</Card.Root>
