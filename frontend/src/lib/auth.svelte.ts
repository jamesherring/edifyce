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

	// Monotonic id of the most recently *initiated* auth operation. Every async
	// operation captures the current id before its first await and only writes
	// `user` if still the latest when it resolves — so a slow in-flight refresh
	// (e.g. the initial init() `/users/me`, still unauthenticated) can't clobber a
	// login/logout/profile update that started after it. Synchronous writers bump
	// the id to invalidate any refresh already in flight.
	let latestOp = 0;
	const nextOp = () => ++latestOp;

	async function refresh(): Promise<void> {
		const op = nextOp();
		try {
			const current = await api.me();
			if (op === latestOp) user = current;
		} catch (err) {
			// 401 simply means "not signed in" — anything else is a real failure we
			// still treat as signed-out, but it isn't worth surfacing here.
			if (!(err instanceof ApiError) || err.status !== 401) {
				console.error('Failed to load current user', err);
			}
			if (op === latestOp) user = null;
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
			const op = nextOp();
			await api.login(email, password);
			const current = await api.me();
			if (op === latestOp) user = current;
		},

		async register(email: string, password: string, displayName?: string): Promise<void> {
			const op = nextOp();
			await api.register(email, password, displayName);
			// Registration doesn't create a session, so log in to obtain one.
			await api.login(email, password);
			const current = await api.me();
			if (op === latestOp) user = current;
		},

		async logout(): Promise<void> {
			const op = nextOp();
			try {
				await api.logout();
			} finally {
				if (op === latestOp) user = null;
			}
		},

		/** Reflect a profile change returned by the API into the store. */
		set(updated: User): void {
			nextOp();
			user = updated;
		}
	};
}

export const auth = createAuth();
