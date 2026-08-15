import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api } from './api';

// A minimal Response stand-in: `request` only reads `.ok`, `.status`, `.text()`.
function mockFetch(status: number, bodyText: string) {
	const ok = status >= 200 && status < 300;
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue({ ok, status, text: async () => bodyText })
	);
}

// `api.systems.get` is an ordinary `request()` call, so it exercises the whole
// shared error contract (extractDetail + formatDetail + the non-JSON fallback)
// that every endpoint runs through.
const call = () => api.systems.get('abc');

afterEach(() => vi.unstubAllGlobals());

describe('request success', () => {
	it('parses and returns a JSON body on 2xx', async () => {
		mockFetch(200, JSON.stringify({ id: 'abc', name: 'Peano' }));
		await expect(call()).resolves.toMatchObject({ id: 'abc', name: 'Peano' });
	});
});

describe('request error contract', () => {
	it('surfaces a string `detail` as the ApiError message', async () => {
		mockFetch(404, JSON.stringify({ detail: 'Formal system not found.' }));
		await expect(call()).rejects.toMatchObject({
			name: 'ApiError',
			status: 404,
			message: 'Formal system not found.',
			detail: 'Formal system not found.'
		});
	});

	it('joins a list of Pydantic validation objects by their `msg`', async () => {
		mockFetch(
			422,
			JSON.stringify({
				detail: [
					{ msg: 'field required', loc: ['body', 'name'] },
					{ msg: 'too long', loc: ['body', 'slug'] }
				]
			})
		);
		await expect(call()).rejects.toMatchObject({
			status: 422,
			message: 'field required\ntoo long'
		});
	});

	it('joins a list of plain strings (our compile-error path)', async () => {
		mockFetch(422, JSON.stringify({ detail: ['line 1 bad', 'line 2 bad'] }));
		await expect(call()).rejects.toMatchObject({ message: 'line 1 bad\nline 2 bad' });
	});

	it('reads `reason` out of a fastapi-users { code, reason } detail', async () => {
		mockFetch(400, JSON.stringify({ detail: { code: 'WEAK', reason: 'Password too short.' } }));
		await expect(call()).rejects.toMatchObject({ message: 'Password too short.' });
	});

	it('falls back to a status message when the error body has no detail', async () => {
		mockFetch(401, '');
		await expect(call()).rejects.toMatchObject({
			status: 401,
			message: 'Request failed with status 401'
		});
	});
});

describe('non-JSON responses', () => {
	it('wraps an HTML/SPA-fallback body on an otherwise-ok response', async () => {
		mockFetch(200, '<!doctype html><title>index</title>');
		await expect(call()).rejects.toMatchObject({
			status: 200,
			message: 'The backend returned an unexpected non-JSON response.'
		});
	});

	it('wraps a non-JSON error page and keeps the raw text as detail', async () => {
		mockFetch(500, '<html>proxy error</html>');
		await expect(call()).rejects.toMatchObject({
			status: 500,
			message: 'Request failed with status 500.',
			detail: '<html>proxy error</html>'
		});
	});
});

describe('unreachable backend', () => {
	it('reports a status-0 ApiError when fetch itself rejects', async () => {
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
		const err = await call().catch((e) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect(err.status).toBe(0);
		expect(err.message).toMatch(/Could not reach the backend/);
	});
});
