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

/** Raised when the backend answers with a non-2xx status. */
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
	const body = text ? JSON.parse(text) : null;

	if (!response.ok) {
		throw new ApiError(response.status, body?.detail ?? body, describeError(body));
	}

	return body as T;
}

function describeError(body: unknown): string | undefined {
	if (body && typeof body === 'object' && 'detail' in body) {
		const detail = (body as { detail: unknown }).detail;
		if (Array.isArray(detail)) return detail.join('\n');
		if (typeof detail === 'string') return detail;
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
