import { api, ApiError, type User } from '$lib/api';

/**
 * Reactive authentication state, shared across the app.
 *
 * The session itself lives in an httponly cookie the browser sends automatically
 * — this store only mirrors *who* is signed in (fetched from `/users/me`) so the
 * UI can react. `ready` gates rendering until the first `/users/me` resolves, so
 * the header doesn't flash "Log in" before we know the user is already signed in.
 */
function createAuth() {
	let user = $state<User | null>(null);
	let ready = $state(false);

	async function refresh(): Promise<void> {
		try {
			user = await api.me();
		} catch (err) {
			// 401 simply means "not signed in" — anything else is a real failure we
			// still treat as signed-out, but it isn't worth surfacing here.
			if (!(err instanceof ApiError) || err.status !== 401) {
				console.error('Failed to load current user', err);
			}
			user = null;
		} finally {
			ready = true;
		}
	}

	return {
		get user() {
			return user;
		},
		get ready() {
			return ready;
		},

		/** Load the current user once, on app start. */
		init: refresh,
		refresh,

		async login(email: string, password: string): Promise<void> {
			await api.login(email, password);
			user = await api.me();
		},

		async register(email: string, password: string, displayName?: string): Promise<void> {
			await api.register(email, password, displayName);
			// Registration doesn't create a session, so log in to obtain one.
			await api.login(email, password);
			user = await api.me();
		},

		async logout(): Promise<void> {
			try {
				await api.logout();
			} finally {
				user = null;
			}
		},

		/** Reflect a profile change returned by the API into the store. */
		set(updated: User): void {
			user = updated;
		}
	};
}

export const auth = createAuth();
