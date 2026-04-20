"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  target: number;
  durationMs?: number;
  className?: string;
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function formatNumber(n: number): string {
  return n.toLocaleString("en-US");
}

export default function StatCounter({ target, durationMs = 1200, className }: Props) {
  const [value, setValue] = useState<number>(() => (prefersReducedMotion() ? target : 0));
  const observerRef = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    if (prefersReducedMotion()) {
      setValue(target);
      return;
    }
    const node = observerRef.current;
    if (!node) return;

    let rafId: number | null = null;
    let started = false;

    const runCountUp = () => {
      const start = performance.now();
      const step = (now: number) => {
        const elapsed = now - start;
        const progress = Math.min(1, elapsed / durationMs);
        const eased = 1 - Math.pow(1 - progress, 3);
        setValue(Math.round(eased * target));
        if (progress < 1) rafId = requestAnimationFrame(step);
      };
      rafId = requestAnimationFrame(step);
    };

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && !started) {
            started = true;
            runCountUp();
            io.disconnect();
            return;
          }
        }
      },
      { threshold: 0.3 },
    );
    io.observe(node);
    return () => {
      io.disconnect();
      if (rafId !== null) cancelAnimationFrame(rafId);
    };
  }, [target, durationMs]);

  return (
    <span
      ref={observerRef}
      className={className}
      aria-live="polite"
      aria-atomic="true"
    >
      {formatNumber(value)}
    </span>
  );
}
