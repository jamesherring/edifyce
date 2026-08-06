import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import Typeset from './Typeset.svelte';

describe('a typeset line', () => {
	it('sets TeX as mathematics', () => {
		render(Typeset, { props: { tex: '\\sqrt{2} \\in \\mathbb{R}' } });

		// `.katex-html` is the visual rendering; the source is still in the DOM
		// beside it, inside KaTeX's MathML `<annotation>`, which is what makes the
		// mathematics readable to a screen reader and copyable as TeX.
		expect(document.querySelector('.katex-html')).not.toBeNull();
		expect(document.querySelector('.katex .mroot, .katex .sqrt')).not.toBeNull();
	});

	it('falls back to the source when KaTeX will not parse it', () => {
		// A projection is derived per production from a token map nobody checked
		// against a TeX parser, so this is expected rather than exceptional — and
		// the readable outcome is the source, not an error over the whole line.
		render(Typeset, { props: { tex: '\\notamacro{' } });

		expect(document.querySelector('.katex')).toBeNull();
		expect(screen.getByText('\\notamacro{')).toBeInTheDocument();
	});
});
