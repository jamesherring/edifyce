<script lang="ts">
	import { onMount } from 'svelte';

	// A faint, fixed, non-interactive background texture drawn on a canvas.
	// One motif per design variant; kept low-contrast so every route stays legible.
	let { kind }: { kind: 'penrose' | 'chalk' | 'golden' | 'cardioid' } = $props();

	let canvas: HTMLCanvasElement;

	function penrose(ctx: CanvasRenderingContext2D, w: number, h: number) {
		const phi = (1 + Math.sqrt(5)) / 2;
		const R = Math.hypot(w, h) * 0.62;
		type C = { re: number; im: number };
		const c = (re: number, im: number): C => ({ re, im });
		const lerp = (a: C, b: C, t: number): C => c(a.re + (b.re - a.re) * t, a.im + (b.im - a.im) * t);
		let tris: [number, C, C, C][] = [];
		for (let i = 0; i < 10; i++) {
			let b = c(R * Math.cos(((2 * i - 1) * Math.PI) / 10), R * Math.sin(((2 * i - 1) * Math.PI) / 10));
			let d = c(R * Math.cos(((2 * i + 1) * Math.PI) / 10), R * Math.sin(((2 * i + 1) * Math.PI) / 10));
			if (i % 2 === 0) [b, d] = [d, b];
			tris.push([0, c(0, 0), b, d]);
		}
		for (let g = 0; g < 5; g++) {
			const nx: [number, C, C, C][] = [];
			for (const [col, A, B, D] of tris) {
				if (col === 0) {
					const P = lerp(A, B, 1 / phi);
					nx.push([0, D, P, B], [1, P, D, A]);
				} else {
					const Q = lerp(B, A, 1 / phi);
					const Rr = lerp(B, D, 1 / phi);
					nx.push([1, Rr, D, A], [1, Q, Rr, B], [0, Rr, Q, A]);
				}
			}
			tris = nx;
		}
		ctx.translate(w / 2, h / 2);
		ctx.lineWidth = 0.8;
		ctx.strokeStyle = 'rgba(28,27,24,0.07)';
		for (const [, , B, D] of tris) {
			ctx.beginPath();
			ctx.moveTo(B.re, B.im);
			ctx.lineTo(D.re, D.im);
			ctx.stroke();
		}
		ctx.setTransform(1, 0, 0, 1, 0, 0);
	}

	function chalk(ctx: CanvasRenderingContext2D, w: number, h: number) {
		ctx.strokeStyle = 'rgba(237,234,226,0.10)';
		ctx.lineWidth = 1.6;
		const rings = [
			{ x: w * 0.86, y: h * 0.16, r: Math.min(w, h) * 0.26 },
			{ x: w * 0.1, y: h * 0.82, r: Math.min(w, h) * 0.17 }
		];
		for (const ring of rings) {
			ctx.beginPath();
			ctx.arc(ring.x, ring.y, ring.r, 0, 2 * Math.PI);
			ctx.stroke();
			for (let i = 0; i < 12; i++) {
				const a = (i / 12) * 2 * Math.PI;
				ctx.beginPath();
				ctx.moveTo(ring.x + ring.r * Math.cos(a), ring.y + ring.r * Math.sin(a));
				ctx.lineTo(ring.x + (ring.r + 8) * Math.cos(a), ring.y + (ring.r + 8) * Math.sin(a));
				ctx.stroke();
			}
		}
	}

	function golden(ctx: CanvasRenderingContext2D, w: number, h: number) {
		const phi = (1 + Math.sqrt(5)) / 2;
		const cx = w * 0.82;
		const cy = h * 0.72;
		const a = Math.min(w, h) * 0.44;
		const b = Math.log(phi) / (Math.PI / 2);
		ctx.lineWidth = 1;
		ctx.strokeStyle = 'rgba(154,123,63,0.09)';
		for (let i = 0; i < 5; i++) {
			const rw = a * 1.7 * Math.pow(1 / phi, i);
			const rh = rw / phi;
			ctx.strokeRect(cx - rw * 0.66, cy - rh * 0.66, rw, rh);
		}
		ctx.lineWidth = 2.2;
		ctx.strokeStyle = 'rgba(154,123,63,0.16)';
		ctx.beginPath();
		let first = true;
		for (let th = 0.4; th > -7.2 * Math.PI; th -= 0.04) {
			const r = a * Math.exp(b * th);
			const px = cx + r * Math.cos(th);
			const py = cy + r * Math.sin(th);
			if (first) {
				ctx.moveTo(px, py);
				first = false;
			} else ctx.lineTo(px, py);
		}
		ctx.stroke();
	}

	function cardioid(ctx: CanvasRenderingContext2D, w: number, h: number) {
		const N = 150;
		const factor = 2;
		const cx = w * 0.74;
		const cy = h * 0.42;
		const R = Math.min(w, h) * 0.42;
		ctx.strokeStyle = 'rgba(108,143,224,0.14)';
		ctx.lineWidth = 0.7;
		for (let i = 0; i < N; i++) {
			const a1 = (i / N) * 2 * Math.PI - Math.PI / 2;
			const j = (i * factor) % N;
			const a2 = (j / N) * 2 * Math.PI - Math.PI / 2;
			ctx.beginPath();
			ctx.moveTo(cx + R * Math.cos(a1), cy + R * Math.sin(a1));
			ctx.lineTo(cx + R * Math.cos(a2), cy + R * Math.sin(a2));
			ctx.stroke();
		}
		ctx.strokeStyle = 'rgba(108,143,224,0.10)';
		ctx.lineWidth = 1;
		ctx.beginPath();
		ctx.arc(cx, cy, R, 0, 2 * Math.PI);
		ctx.stroke();
	}

	const renderers = { penrose, chalk, golden, cardioid };

	function draw() {
		if (!canvas) return;
		const dpr = Math.min(window.devicePixelRatio || 1, 2);
		const w = window.innerWidth;
		const h = window.innerHeight;
		canvas.width = w * dpr;
		canvas.height = h * dpr;
		canvas.style.width = `${w}px`;
		canvas.style.height = `${h}px`;
		const ctx = canvas.getContext('2d');
		if (!ctx) return;
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		ctx.clearRect(0, 0, w, h);
		renderers[kind](ctx, w, h);
	}

	onMount(() => {
		draw();
		window.addEventListener('resize', draw);
		return () => window.removeEventListener('resize', draw);
	});
</script>

<canvas bind:this={canvas} aria-hidden="true" class="pointer-events-none fixed inset-0 z-0"></canvas>
