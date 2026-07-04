// Base URL of the Edifyce FastAPI backend.
//
// Defaults to an empty string, i.e. same-origin relative requests. This is the
// safe default for production, where the built bundle is served by FastAPI (or
// behind a reverse proxy) on the same origin. In development the SvelteKit dev
// server proxies the API paths to the backend (see vite.config.ts), so relative
// requests work there too.
//
// Set `VITE_API_BASE_URL` at build/dev time to target a backend on a different
// origin (that origin must then be allowed by the backend's CORS config).
const raw = import.meta.env.VITE_API_BASE_URL ?? '';

export const API_BASE_URL = raw.replace(/\/+$/, '');
