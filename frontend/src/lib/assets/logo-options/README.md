# Logo / favicon options

Five candidate site icons for Edifyce — each a self-contained rounded "ink"
badge with a single bold, mathematically-themed glyph. They are drawn as
vector paths (no web fonts) with heavy strokes so they stay legible at
favicon size (16px), and the badge is opaque with a faint light inner border
so it reads on both light and dark browser tabs.

| File | Glyph | Meaning |
|---|---|---|
| `1-turnstile.svg` | ⊢ | Provability / entailment — the sequent-calculus "proves" symbol |
| `2-therefore.svg` | ∴ | Therefore — marks a conclusion |
| `3-sigma.svg` | Σ | Summation (matches the header mark) |
| `4-forall.svg` | ∀ | Universal quantifier |
| `5-integral.svg` | ∫ | Integral |

Not yet wired in. To adopt one as the favicon, point
`src/routes/+layout.svelte` at it, e.g.:

```svelte
import favicon from '$lib/assets/logo-options/1-turnstile.svg';
```
