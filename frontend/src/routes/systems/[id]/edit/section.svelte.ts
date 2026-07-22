import { runMutation } from './crud';

// The four child-CRUD calls every part shares (see `partCrud` in $lib/api).
// Typed on the payload the section builds; the real crud's update accepts a
// Partial of it, which is assignable here.
export interface PartCrud<Payload> {
	create(systemId: string, payload: Payload): Promise<unknown>;
	update(systemId: string, id: string, payload: Payload): Promise<unknown>;
	remove(systemId: string, id: string): Promise<unknown>;
	reorder(systemId: string, ids: string[]): Promise<unknown>;
}

export interface SectionController<Item extends { id: string }> {
	/** Whether the edit sheet is open (settable so `onOpenChange` can close it). */
	open: boolean;
	/** The item being edited, or null when adding a new one. */
	readonly editing: Item | null;
	/** A create/update/delete is in flight. */
	readonly saving: boolean;
	/** A reorder is in flight (disables the row controls). */
	readonly busy: boolean;
	openNew(): void;
	openEdit(item: Item): void;
	save(): Promise<void>;
	del(): Promise<void>;
	reorder(ids: string[]): Promise<void>;
}

/**
 * The open/editing/saving/busy state and the create/update/delete/reorder
 * orchestration every `*Section.svelte` shares. The section supplies only what
 * differs: its `crud` namespace, the singular `noun` for toast messages, and the
 * form glue — `fill` (populate the form from an item, or reset it for a new one),
 * `payload` (build the write body from the form), and `canSave`.
 */
export function createSectionController<Item extends { id: string }, Payload>(opts: {
	crud: PartCrud<Payload>;
	// Thunks, not values: `systemId` (and, if a parent ever swaps it, `onChanged`)
	// are props that can change while this section stays mounted — reading them
	// lazily keeps every call pointed at the current one.
	systemId: () => string;
	noun: string;
	onChanged: () => Promise<void> | void;
	canSave: () => boolean;
	fill: (item: Item | null) => void;
	payload: () => Payload;
}): SectionController<Item> {
	let open = $state(false);
	let editing = $state<Item | null>(null);
	let saving = $state(false);
	let busy = $state(false);

	async function afterWrite(ok: boolean): Promise<void> {
		saving = false;
		if (ok) {
			open = false;
			await opts.onChanged();
		}
	}

	return {
		get open() {
			return open;
		},
		set open(value: boolean) {
			open = value;
		},
		get editing() {
			return editing;
		},
		get saving() {
			return saving;
		},
		get busy() {
			return busy;
		},
		openNew() {
			editing = null;
			opts.fill(null);
			open = true;
		},
		openEdit(item: Item) {
			editing = item;
			opts.fill(item);
			open = true;
		},
		async save() {
			if (!opts.canSave() || saving) return;
			const item = editing;
			saving = true;
			const ok = await runMutation(
				() =>
					item
						? opts.crud.update(opts.systemId(), item.id, opts.payload())
						: opts.crud.create(opts.systemId(), opts.payload()),
				item ? `${opts.noun} updated.` : `${opts.noun} added.`
			);
			await afterWrite(ok);
		},
		async del() {
			const item = editing;
			if (!item || saving) return;
			saving = true;
			const ok = await runMutation(
				() => opts.crud.remove(opts.systemId(), item.id),
				`${opts.noun} deleted.`
			);
			await afterWrite(ok);
		},
		async reorder(ids: string[]) {
			busy = true;
			if (await runMutation(() => opts.crud.reorder(opts.systemId(), ids))) await opts.onChanged();
			busy = false;
		}
	};
}
