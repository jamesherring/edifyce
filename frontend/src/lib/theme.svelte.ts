import { browser } from '$app/environment';

type Theme = 'light' | 'dark';

function createTheme() {
	// Initialise from the class the pre-hydration script in app.html already
	// applied, so the toggle icon matches the rendered theme from the first paint.
	let current = $state<Theme>(
		browser && document.documentElement.classList.contains('dark') ? 'dark' : 'light'
	);

	function apply(theme: Theme) {
		current = theme;
		if (browser) {
			document.documentElement.classList.toggle('dark', theme === 'dark');
			localStorage.setItem('theme', theme);
		}
	}

	return {
		get value() {
			return current;
		},
		/** Read the saved / system preference. Call once on mount. */
		init() {
			if (!browser) return;
			const saved = localStorage.getItem('theme') as Theme | null;
			const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
			apply(saved ?? (prefersDark ? 'dark' : 'light'));
		},
		toggle() {
			apply(current === 'dark' ? 'light' : 'dark');
		}
	};
}

export const theme = createTheme();
