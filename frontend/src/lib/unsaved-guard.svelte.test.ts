import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createUnsavedGuard } from './unsaved-guard.svelte';
import { beforeNavigate, goto } from '$app/navigation';

vi.mock('$app/navigation', () => ({ beforeNavigate: vi.fn(), goto: vi.fn() }));

const beforeNavigateMock = beforeNavigate as unknown as ReturnType<typeof vi.fn>;
const gotoMock = goto as unknown as ReturnType<typeof vi.fn>;

type Navigation = { type: string; to: { url: URL } | null; cancel: ReturnType<typeof vi.fn> };

/** Build the guard and hand back the `beforeNavigate` callback it registered. */
function setup(isDirty: () => boolean) {
	const guard = createUnsavedGuard(isDirty);
	const handler = beforeNavigateMock.mock.calls.at(-1)![0] as (n: Navigation) => void;
	return { guard, handler };
}

function navigation(url = 'http://localhost/proofs', type = 'link'): Navigation {
	return { type, to: { url: new URL(url) }, cancel: vi.fn() };
}

beforeEach(() => vi.clearAllMocks());

describe('createUnsavedGuard', () => {
	it('lets a navigation through when there is nothing to lose', () => {
		const { guard, handler } = setup(() => false);
		const nav = navigation();
		handler(nav);
		expect(nav.cancel).not.toHaveBeenCalled();
		expect(guard.prompting).toBe(false);
	});

	it('blocks a navigation with unsaved edits and asks first', () => {
		const { guard, handler } = setup(() => true);
		const nav = navigation();
		handler(nav);
		expect(nav.cancel).toHaveBeenCalledOnce();
		expect(guard.prompting).toBe(true);
	});

	it('reads dirtiness at navigation time, not at construction', () => {
		let dirty = false;
		const { guard, handler } = setup(() => dirty);
		handler(navigation());
		expect(guard.prompting).toBe(false);

		dirty = true;
		handler(navigation());
		expect(guard.prompting).toBe(true);
	});

	it('resumes the blocked navigation when the user chooses to leave', () => {
		const { guard, handler } = setup(() => true);
		handler(navigation('http://localhost/systems/abc'));

		guard.leave();

		expect(guard.prompting).toBe(false);
		expect(gotoMock).toHaveBeenCalledOnce();
		expect(String(gotoMock.mock.calls[0][0])).toBe('http://localhost/systems/abc');
	});

	it('stops guarding once the user has chosen to leave, so the retry gets through', () => {
		const { guard, handler } = setup(() => true);
		handler(navigation());
		guard.leave();

		// leave() calls goto(), which re-enters this handler. Blocking a second
		// time would mean the navigation never actually happens.
		const retry = navigation();
		handler(retry);
		expect(retry.cancel).not.toHaveBeenCalled();
	});

	it('stays put without navigating when the user cancels', () => {
		const { guard, handler } = setup(() => true);
		handler(navigation());

		guard.stay();

		expect(guard.prompting).toBe(false);
		expect(gotoMock).not.toHaveBeenCalled();
	});

	it('stands down for a navigation the page makes itself', () => {
		const { guard, handler } = setup(() => true);
		guard.allow();

		const nav = navigation();
		handler(nav);

		// Deleting the thing being edited navigates away on purpose; "unsaved
		// changes" is moot by then.
		expect(nav.cancel).not.toHaveBeenCalled();
		expect(guard.prompting).toBe(false);
	});

	it('hands a tab close to the browser rather than a dialog nobody would see', () => {
		const { guard, handler } = setup(() => true);
		const nav: Navigation = { type: 'leave', to: null, cancel: vi.fn() };

		handler(nav);

		// Cancelling a `leave` is what triggers the browser's own prompt.
		expect(nav.cancel).toHaveBeenCalledOnce();
		expect(guard.prompting).toBe(false);
	});
});
