// Adds the jest-dom matchers (toBeInTheDocument, toHaveTextContent, …) to
// Vitest's `expect`, and runs in the jsdom client project (see vite.config.ts).
import '@testing-library/jest-dom/vitest';

// jsdom implements no layout, so `scrollIntoView` is absent — bits-ui's command
// list calls it (inside a scheduled callback that can fire around teardown) to
// keep the active item in view. Define it unconditionally as a no-op so picker
// tests never hit an "scrollIntoView is not a function" unhandled rejection,
// which would flake CI even though every test passes.
Element.prototype.scrollIntoView = function scrollIntoView() {};
