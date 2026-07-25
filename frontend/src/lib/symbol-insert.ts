/** A text field the symbol palette can insert into. */
export type TextField = HTMLInputElement | HTMLTextAreaElement;

/** Marks a field as a symbol-palette target; the palette tracks these by selector. */
export const SYMBOL_FIELD_SELECTOR = 'input[data-symbol-field], textarea[data-symbol-field]';

export function isTextField(node: EventTarget | null): node is TextField {
	return node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement;
}

/**
 * Insert `text` at the field's caret, replacing any selection, and leave the
 * caret after it with the field focused.
 */
export function insertAtCaret(el: TextField, text: string): void {
	el.focus();

	// `insertText` goes through the browser's own editing pipeline, so Ctrl-Z
	// still undoes the insertion — assigning to `value` would wipe the undo
	// stack. It's deprecated but universally implemented for text fields; jsdom
	// lacks it entirely, hence the manual splice below.
	if (document.execCommand?.('insertText', false, text)) return;

	const start = el.selectionStart ?? el.value.length;
	const end = el.selectionEnd ?? start;
	el.value = el.value.slice(0, start) + text + el.value.slice(end);
	const caret = start + text.length;
	el.setSelectionRange(caret, caret);
	// Svelte's `bind:value` listens for input events; a direct write is invisible
	// to the binding without one.
	el.dispatchEvent(new Event('input', { bubbles: true }));
}
