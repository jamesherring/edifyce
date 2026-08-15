// Adds the jest-dom matchers (toBeInTheDocument, toHaveTextContent, …) to
// Vitest's `expect`, and runs in the jsdom client project (see vite.config.ts).
import '@testing-library/jest-dom/vitest';

// jsdom implements no layout, so `scrollIntoView` is absent — bits-ui's command
// list calls it (inside a scheduled callback that can fire around teardown) to
// keep the active item in view. Define it unconditionally as a no-op so picker
// tests never hit an "scrollIntoView is not a function" unhandled rejection,
// which would flake CI even though every test passes.
Element.prototype.scrollIntoView = function scrollIntoView() {};

// bits-ui's dialog/popover body-scroll-lock schedules a ~24ms setTimeout to
// restore <body> styles when a locked overlay (an EditSheet, a combobox popover)
// unmounts. A test that leaves an overlay open unmounts it during cleanup, which
// schedules that timer; if it fires after jsdom tears the file's `document` down
// it throws "document is not defined" as an uncaught exception and fails the run
// (exit 1) even though every test passed. Unmount now and wait the timer out,
// while `document` still exists. Calling cleanup() here is order-independent: if
// testing-library's own afterEach already ran, this is a no-op and the wait still
// flushes the timer it scheduled.
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/svelte';

afterEach(async () => {
	cleanup();
	await new Promise((resolve) => setTimeout(resolve, 30));
});
