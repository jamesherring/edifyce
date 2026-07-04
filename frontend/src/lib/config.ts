// Base URL of the Edifyce FastAPI backend.
//
// Override at build/dev time with the `VITE_API_BASE_URL` environment variable
// (see .env.example). Defaults to the local uvicorn address. Set it to an empty
// string to issue same-origin requests — useful when the built bundle is served
// by FastAPI itself.
const raw = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export const API_BASE_URL = raw.replace(/\/+$/, '');
