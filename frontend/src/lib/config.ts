// Base URL of the Edifyce FastAPI backend.
//
// Defaults to an empty string, i.e. same-origin relative requests. The client
// prefixes every request with `/api` (see api.ts), so this is only the origin.
// That empty default is the safe one for production, where the built bundle is
// served by FastAPI (or behind a reverse proxy) on the same origin. In
// development the SvelteKit dev server proxies `/api` to the backend (see
// vite.config.ts), so relative requests work there too.
//
// Set `VITE_API_BASE_URL` at build/dev time to target a backend on a different
// origin (that origin must then be allowed by the backend's CORS config).
const raw = import.meta.env.VITE_API_BASE_URL ?? '';

export const API_BASE_URL = raw.replace(/\/+$/, '');
