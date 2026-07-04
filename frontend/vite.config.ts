import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},

			// The app is a static single-page app that talks to the FastAPI backend
			// over HTTP. `fallback` makes every route resolve to index.html so client
			// side routing works when the bundle is served by any static host — or by
			// FastAPI itself (see app/main.py).
			adapter: adapter({
				fallback: 'index.html'
			})
		})
	]
});
