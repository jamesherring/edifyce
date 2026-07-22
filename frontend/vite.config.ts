/// <reference types="vitest/config" />
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { svelteTesting } from '@testing-library/svelte/vite';
import { defineConfig, loadEnv } from 'vite';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig(({ mode }) => {
	const env = loadEnv(mode, '.', '');

	// Where the dev server proxies API calls. Because the app makes same-origin
	// (relative) requests by default, the dev server forwards the backend paths
	// to the running FastAPI process — no CORS or absolute URL needed in dev.
	const proxyTarget = env.VITE_API_PROXY_TARGET || 'http://localhost:8000';
	const proxy = Object.fromEntries(
		['/health', '/formal-systems', '/proofs', '/auth', '/users'].map((path) => [
			path,
			{ target: proxyTarget, changeOrigin: true }
		])
	);

	return {
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
		],
		server: { proxy },
		// One jsdom project so both pure-unit and component tests share a browser
		// -like env (format.ts/api.ts touch window.location; components render into
		// the DOM). `extends: true` inherits the sveltekit plugin above, so `$lib`
		// / `$app` aliases resolve; svelteTesting() is scoped here so dev and build
		// builds stay untouched.
		test: {
			projects: [
				{
					extends: true,
					plugins: [svelteTesting()],
					test: {
						name: 'client',
						environment: 'jsdom',
						clearMocks: true,
						setupFiles: ['./src/vitest-setup-client.ts'],
						include: ['src/**/*.{test,spec}.ts']
					}
				}
			]
		}
	};
});
