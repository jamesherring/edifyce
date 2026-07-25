import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/svelte';
import CodeEditor from './code-editor.svelte';

describe('CodeEditor line-number gutter', () => {
	it('renders no gutter by default', () => {
		const { container } = render(CodeEditor, { value: 'a\nb\nc' });
		// Plain textarea, no aria-hidden gutter column.
		expect(container.querySelector('[aria-hidden="true"]')).toBeNull();
	});

	it('renders one gutter number per line when enabled', () => {
		const { container } = render(CodeEditor, {
			value: 'line one\nline two\nline three',
			showLineNumbers: true
		});
		const gutter = container.querySelector('[aria-hidden="true"]');
		expect(gutter).not.toBeNull();
		const numbers = gutter!.querySelectorAll(':scope > div');
		expect(numbers).toHaveLength(3);
		expect(Array.from(numbers).map((n) => n.textContent?.trim())).toEqual(['1', '2', '3']);
	});

	it('always shows at least line 1 for empty content', () => {
		const { container } = render(CodeEditor, { value: '', showLineNumbers: true });
		const numbers = container.querySelectorAll('[aria-hidden="true"] > div');
		expect(numbers).toHaveLength(1);
		expect(numbers[0].textContent?.trim()).toBe('1');
	});

	it('tints a gutter number by its line status', () => {
		const { container } = render(CodeEditor, {
			value: 'ok line\nbad line',
			showLineNumbers: true,
			lineStatuses: ['ok', 'error']
		});
		const numbers = container.querySelectorAll('[aria-hidden="true"] > div');
		expect(numbers[0].className).toContain('text-success');
		expect(numbers[1].className).toContain('text-destructive');
	});

	it('shows citation numbers when given, blanking lines that have none', () => {
		// The blank line is uncitable, so the step after it stays line 2 — the row
		// position (3) is exactly what a reference must not be written against.
		const { container } = render(CodeEditor, {
			value: 'a [HYP]\n\nb [MP, 1]',
			showLineNumbers: true,
			lineNumbers: [1, null, 2]
		});
		const numbers = container.querySelectorAll('[aria-hidden="true"] > div');
		expect(Array.from(numbers).map((n) => n.textContent?.trim())).toEqual(['1', '', '2']);
	});

	it('falls back to row positions when citation numbers are unknown', () => {
		// An empty array means the last result no longer lines up with the text
		// (mid-edit); plain positions beat stale numbers.
		const { container } = render(CodeEditor, {
			value: 'a\n\nb',
			showLineNumbers: true,
			lineNumbers: []
		});
		const numbers = container.querySelectorAll('[aria-hidden="true"] > div');
		expect(Array.from(numbers).map((n) => n.textContent?.trim())).toEqual(['1', '2', '3']);
	});

	it('exposes focusLine to select a given line', () => {
		const { container, component } = render(CodeEditor, {
			value: 'alpha\nbravo\ncharlie',
			showLineNumbers: true
		});
		const textarea = container.querySelector('textarea') as HTMLTextAreaElement;
		// jsdom has no layout, so getComputedStyle/lineHeight is a no-op — the
		// selection is what matters for jumping to a line.
		(component as unknown as { focusLine: (i: number) => void }).focusLine(1);
		// "bravo" spans chars 6..11 ("alpha\n" = 6 chars).
		expect(textarea.selectionStart).toBe(6);
		expect(textarea.selectionEnd).toBe(11);
	});
});
