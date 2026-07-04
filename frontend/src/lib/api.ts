import { API_BASE_URL } from './config';

// ---------------------------------------------------------------------------
// Response shapes — mirror app/schemas.py and the proof `.data()` payload.
// ---------------------------------------------------------------------------

export interface HealthResponse {
	status: string;
}

export interface CompileResponse {
	success: boolean;
	errors: string[];
	system_name: string | null;
	line_type_count: number | null;
	inference_rule_count: number | null;
}

export interface ProofLine {
	valid: boolean;
	behaviour: string | null;
	name: string | null;
	invalid_message: string | null;
	warning_message: string | null;
	reference: string | null;
	label: string | null;
	display: string | null;
	indent: number;
}

export interface ProofData {
	indicator: 'ok' | 'warning' | 'error' | string;
	lines: ProofLine[];
}

export interface VerifyResponse {
	success: boolean;
	errors: string[];
	proof: ProofData | null;
}

/** Raised when the backend answers with a non-2xx status or is unreachable. */
export class ApiError extends Error {
	status: number;
	detail: unknown;

	constructor(status: number, detail: unknown, message?: string) {
		super(message ?? `Request failed with status ${status}`);
		this.name = 'ApiError';
		this.status = status;
		this.detail = detail;
	}
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	let response: Response;
	try {
		response = await fetch(`${API_BASE_URL}${path}`, {
			headers: { 'Content-Type': 'application/json' },
			...init
		});
	} catch (cause) {
		throw new ApiError(
			0,
			cause,
			`Could not reach the backend at ${API_BASE_URL || window.location.origin}. Is it running?`
		);
	}

	const text = await response.text();

	// The body should be JSON, but a proxy error page or the SPA index.html
	// fallback can return HTML. Parse defensively so a non-JSON body surfaces as
	// an ApiError rather than an unwrapped SyntaxError.
	let body: unknown = null;
	if (text) {
		try {
			body = JSON.parse(text);
		} catch {
			throw new ApiError(
				response.status,
				text,
				response.ok
					? 'The backend returned an unexpected non-JSON response.'
					: `Request failed with status ${response.status}.`
			);
		}
	}

	if (!response.ok) {
		const detail = extractDetail(body);
		throw new ApiError(response.status, detail, formatDetail(detail));
	}

	return body as T;
}

function extractDetail(body: unknown): unknown {
	if (body && typeof body === 'object' && 'detail' in body) {
		return (body as { detail: unknown }).detail;
	}
	return body;
}

/**
 * Render a FastAPI `detail` into a readable message. `detail` may be a plain
 * string, a list of strings (our compile-error path), or a list of Pydantic
 * validation-error objects (`{ msg, loc, ... }`).
 */
function formatDetail(detail: unknown): string | undefined {
	if (typeof detail === 'string') return detail;
	if (Array.isArray(detail)) {
		return detail
			.map((item) => {
				if (typeof item === 'string') return item;
				if (item && typeof item === 'object' && 'msg' in item) {
					return String((item as { msg: unknown }).msg);
				}
				return JSON.stringify(item);
			})
			.join('\n');
	}
	return undefined;
}

export const api = {
	health: () => request<HealthResponse>('/health'),

	compile: (code: string) =>
		request<CompileResponse>('/formal-systems/compile', {
			method: 'POST',
			body: JSON.stringify({ code })
		}),

	verify: (systemCode: string, proofText: string) =>
		request<VerifyResponse>('/proofs/verify', {
			method: 'POST',
			body: JSON.stringify({ system_code: systemCode, proof_text: proofText })
		})
};
