// Render the whole app as a client-side SPA. There is no Node server in front
// of the static bundle — data comes from the FastAPI backend over fetch — so
// server-side rendering and prerendering are both disabled.
export const ssr = false;
export const prerender = false;
