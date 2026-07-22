import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { formatDate, formatDuration, timeAgo, timeUntil } from './format';

// A fixed "now" so the relative formatters are deterministic. All the relative
// cases below are expressed as offsets from this instant.
const NOW = new Date('2026-07-22T12:00:00.000Z');
const iso = (msFromNow: number) => new Date(NOW.getTime() + msFromNow).toISOString();
const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

describe('timeAgo', () => {
	beforeEach(() => {
		vi.useFakeTimers();
		vi.setSystemTime(NOW);
	});
	afterEach(() => vi.useRealTimers());

	it('returns "Never" for null/undefined and "—" for an unparseable date', () => {
		expect(timeAgo(null)).toBe('Never');
		expect(timeAgo(undefined)).toBe('Never');
		expect(timeAgo('not a date')).toBe('—');
	});

	it('collapses anything under a minute to "just now"', () => {
		expect(timeAgo(iso(0))).toBe('just now');
		expect(timeAgo(iso(-59 * SECOND))).toBe('just now');
	});

	it('crosses each bucket boundary exactly at the threshold', () => {
		expect(timeAgo(iso(-MINUTE))).toBe('1m ago'); // 60s → minutes
		expect(timeAgo(iso(-59 * MINUTE))).toBe('59m ago');
		expect(timeAgo(iso(-HOUR))).toBe('1h ago'); // 60m → hours
		expect(timeAgo(iso(-23 * HOUR))).toBe('23h ago');
		expect(timeAgo(iso(-DAY))).toBe('1d ago'); // 24h → days
		expect(timeAgo(iso(-29 * DAY))).toBe('29d ago');
		expect(timeAgo(iso(-30 * DAY))).toBe('1mo ago'); // 30d → months
		expect(timeAgo(iso(-11 * 30 * DAY))).toBe('11mo ago');
		expect(timeAgo(iso(-12 * 30 * DAY))).toBe('1y ago'); // 12mo → years
	});
});

describe('timeUntil', () => {
	beforeEach(() => {
		vi.useFakeTimers();
		vi.setSystemTime(NOW);
	});
	afterEach(() => vi.useRealTimers());

	it('returns "—" for null, unparseable, or a non-future time', () => {
		expect(timeUntil(null)).toBe('—');
		expect(timeUntil('nope')).toBe('—');
		expect(timeUntil(iso(0))).toBe('—'); // exactly now is not future
		expect(timeUntil(iso(-MINUTE))).toBe('—'); // past
	});

	it('crosses each future bucket boundary at the threshold', () => {
		expect(timeUntil(iso(30 * SECOND))).toBe('in 30s');
		expect(timeUntil(iso(MINUTE))).toBe('in 1m'); // 60s → minutes
		expect(timeUntil(iso(59 * MINUTE))).toBe('in 59m');
		expect(timeUntil(iso(HOUR))).toBe('in 1h'); // 60m → hours
		expect(timeUntil(iso(23 * HOUR))).toBe('in 23h');
		expect(timeUntil(iso(DAY))).toBe('in 1d'); // 24h → days
	});
});

describe('formatDuration', () => {
	it('shows whole milliseconds under a second', () => {
		expect(formatDuration(0)).toBe('0ms');
		expect(formatDuration(499.6)).toBe('500ms'); // rounds
		expect(formatDuration(999)).toBe('999ms');
	});

	it('shows one decimal of seconds under a minute', () => {
		expect(formatDuration(1000)).toBe('1.0s'); // 1s boundary
		expect(formatDuration(1500)).toBe('1.5s');
		expect(formatDuration(59_900)).toBe('59.9s');
	});

	it('shows minutes and seconds at and above a minute', () => {
		expect(formatDuration(60_000)).toBe('1m 0s'); // 60s boundary
		expect(formatDuration(123_000)).toBe('2m 3s');
	});
});

describe('formatDate', () => {
	it('returns "—" for null/undefined and an unparseable date', () => {
		expect(formatDate(null)).toBe('—');
		expect(formatDate(undefined)).toBe('—');
		expect(formatDate('not a date')).toBe('—');
	});

	it('renders a parseable date via the browser locale (non-empty, not the dash)', () => {
		const rendered = formatDate('2026-07-22T12:00:00.000Z');
		expect(rendered).not.toBe('—');
		expect(rendered.length).toBeGreaterThan(0);
	});
});
