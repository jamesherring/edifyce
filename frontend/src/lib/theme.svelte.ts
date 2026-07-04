import { browser } from '$app/environment';

type Theme = 'light' | 'dark';

function createTheme() {
	let current = $state<Theme>('light');

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
