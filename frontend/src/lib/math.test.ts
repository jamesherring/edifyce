import { describe, expect, it } from 'vitest';
import { preferredNotation } from './math';

describe('preferredNotation', () => {
	it('opens in the system’s own choice where it still has it', () => {
		expect(preferredNotation(['unicode', 'latex'], 'unicode')).toBe('unicode');
	});

	it('prefers a typeset reading when the system has said nothing', () => {
		expect(preferredNotation(['unicode', 'latex'], null)).toBe('latex');
	});

	it('falls back to the source when there is nothing typeset to open in', () => {
		expect(preferredNotation(['unicode'], null)).toBeNull();
		expect(preferredNotation([], null)).toBeNull();
	});

	it('ignores a stored default naming a notation the system no longer has', () => {
		// The setting and the notations are edited apart, so a default outlives
		// what it names; asking for it would only earn an error on every proof.
		// The TeX fallback still applies — this is a missing choice, not a choice
		// of the source.
		expect(preferredNotation(['latex'], 'unicode')).toBe('latex');
		expect(preferredNotation([], 'unicode')).toBeNull();
	});
});
