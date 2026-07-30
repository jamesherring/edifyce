import type { ProductionBinding } from '$lib/api';

/** A production's slot while it is being edited.
 *
 * The API names a scope target by the sibling slot's `var`; the editor refers to
 * it by an editor-local `id` instead. That is what lets a rename carry the
 * declaration with it — the id does not care what the slot is called — and it
 * makes a target that no longer exists unrepresentable rather than something to
 * filter out on the way to the server.
 *
 * An id rather than a reference to the row object, because these rows live in a
 * `$state` array: reading one through the proxy and holding the raw object are
 * two different identities, so `includes` on a mix of the two silently answers
 * false. An id is the same number either way.
 */
export interface SlotRow {
	id: number;
	var: string;
	sort: string;
	/** The ids of the sibling slots this one's binding reaches into. */
	scopes: number[];
}

// Monotonic across every fill, so ids from a previous production can never
// collide with this one's.
let nextId = 0;

export function blankSlot(): SlotRow {
	return { id: nextId++, var: '', sort: '', scopes: [] };
}

/** Stored slots → editable rows, resolving each scope target to its sibling's id. */
export function toSlotRows(bindings: ProductionBinding[]): SlotRow[] {
	const rows: SlotRow[] = bindings.map((b) => ({
		id: nextId++,
		var: b.var,
		sort: b.sort,
		scopes: []
	}));
	const idByVar = new Map(rows.map((row) => [row.var, row.id]));
	bindings.forEach((binding, i) => {
		rows[i].scopes = (binding.scopes_over ?? [])
			.map((target) => idByVar.get(target))
			// A stored scope over a slot the production does not have cannot arrive
			// through the API, which rejects it — but an unresolvable target is
			// dropped rather than trusted, since the alternative is a dangling id.
			.filter((id): id is number => id !== undefined && id !== rows[i].id);
	});
	return rows;
}

/** Editable rows → the API's shape, keeping only slots that are fully named.
 *
 * A scope over a row that did not survive that filter goes with it: an unnamed
 * slot is not a slot yet, so nothing can bind over it.
 */
export function toProductionBindings(slots: SlotRow[]): ProductionBinding[] {
	const named = slots.filter((slot) => slot.var.trim() && slot.sort.trim());
	const varById = new Map(named.map((slot) => [slot.id, slot.var.trim()]));
	return named.map((slot) => ({
		var: slot.var.trim(),
		sort: slot.sort.trim(),
		scopes_over: [
			...new Set(
				slot.scopes
					.filter((id) => id !== slot.id)
					.map((id) => varById.get(id))
					.filter((name): name is string => name !== undefined)
			)
		]
	}));
}
