import { beforeNavigate, goto } from '$app/navigation';

export interface UnsavedGuard {
	/** True while a blocked navigation is waiting on the user's answer. */
	readonly prompting: boolean;
	/** Discard the edits and continue to wherever the user was heading. */
	leave(): void;
	/** Stay put and keep editing. */
	stay(): void;
	/** Stand down for a navigation the page itself is making — after a save, or
	 *  after deleting the thing being edited, where "unsaved changes" is moot. */
	allow(): void;
}

/**
 * Stop an in-progress edit being lost to a stray click on a nav link.
 *
 * Must be called during component init (it registers `beforeNavigate`). The page
 * supplies `isDirty` as a thunk so the guard always reads the current value
 * rather than a snapshot, and renders a dialog off `prompting`.
 */
export function createUnsavedGuard(isDirty: () => boolean): UnsavedGuard {
	let prompting = $state(false);
	let target: URL | null = null;
	// Not reactive: nothing renders off it, and it must not re-run anything.
	let allowed = false;

	beforeNavigate((navigation) => {
		if (allowed || !isDirty()) return;
		navigation.cancel();
		// Closing the tab can't wait on a dialog; cancelling a `leave` hands off to
		// the browser's own "leave site?" prompt, which is the only option there.
		if (navigation.type !== 'leave' && navigation.to) {
			target = navigation.to.url;
			prompting = true;
		}
	});

	return {
		get prompting() {
			return prompting;
		},
		leave() {
			allowed = true;
			prompting = false;
			const url = target;
			target = null;
			if (url) goto(url);
		},
		stay() {
			prompting = false;
			target = null;
		},
		allow() {
			allowed = true;
		}
	};
}
