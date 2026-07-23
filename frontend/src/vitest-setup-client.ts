// Adds the jest-dom matchers (toBeInTheDocument, toHaveTextContent, …) to
// Vitest's `expect`, and runs in the jsdom client project (see vite.config.ts).
import '@testing-library/jest-dom/vitest';

// jsdom implements no layout, so `scrollIntoView` is absent — bits-ui's command
// list calls it while keeping the active item in view. Stub it so component tests
// exercising the picker don't hit an unhandled rejection.
if (!Element.prototype.scrollIntoView) {
	Element.prototype.scrollIntoView = () => {};
}
