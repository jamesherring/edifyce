import { toast } from 'svelte-sonner';

// Every mutation should surface its outcome through one of these, so success and
// failure feedback stays consistent across the app.
export function toastSuccess(message: string) {
	toast.success(message);
}

export function toastError(message: string) {
	toast.error(message);
}
