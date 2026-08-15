// Shared, dependency-free formatters for timestamps and durations. Keep display
// formatting here so pages and components never hand-roll their own.

/** Relative past time, e.g. "5m ago" / "3h ago" / "2d ago". "Never" for null. */
export function timeAgo(dateStr: string | null | undefined): string {
	if (!dateStr) return 'Never';
	const then = new Date(dateStr).getTime();
	if (Number.isNaN(then)) return '—';
	const seconds = Math.floor((Date.now() - then) / 1000);
	if (seconds < 60) return 'just now';
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return `${minutes}m ago`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h ago`;
	const days = Math.floor(hours / 24);
	if (days < 30) return `${days}d ago`;
	const months = Math.floor(days / 30);
	if (months < 12) return `${months}mo ago`;
	return `${Math.floor(months / 12)}y ago`;
}

/** Relative future time, e.g. "in 5m". "—" for null/past. */
export function timeUntil(dateStr: string | null | undefined): string {
	if (!dateStr) return '—';
	const target = new Date(dateStr).getTime();
	if (Number.isNaN(target)) return '—';
	const seconds = Math.floor((target - Date.now()) / 1000);
	if (seconds <= 0) return '—';
	if (seconds < 60) return `in ${seconds}s`;
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return `in ${minutes}m`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `in ${hours}h`;
	return `in ${Math.floor(hours / 24)}d`;
}

/** Human duration from milliseconds, e.g. "500ms" / "1.5s" / "2m 3s". */
export function formatDuration(ms: number): string {
	if (ms < 1000) return `${Math.round(ms)}ms`;
	const seconds = ms / 1000;
	if (seconds < 60) return `${seconds.toFixed(1)}s`;
	const minutes = Math.floor(seconds / 60);
	const rem = Math.round(seconds % 60);
	return `${minutes}m ${rem}s`;
}

/** Absolute local date-time via the browser locale. */
export function formatDate(dateStr: string | null | undefined): string {
	if (!dateStr) return '—';
	const date = new Date(dateStr);
	if (Number.isNaN(date.getTime())) return '—';
	return date.toLocaleString();
}
