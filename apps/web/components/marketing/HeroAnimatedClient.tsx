"use client";

import { useEffect, useRef, type ReactNode } from "react";

interface HeroAnimatedClientProps {
  children: ReactNode;
}

/**
 * Thin GSAP wrapper around the hero copy + demo.
 *
 * The children arrive with a .marketing-fade-in CSS animation already
 * applied, so first paint is graceful even if JS is slow. GSAP then
 * upgrades it to a coordinated timeline if available at runtime. We
 * load it dynamically so the marketing bundle stays lean when GSAP is
 * already shared elsewhere.
 */
export default function HeroAnimatedClient({ children }: HeroAnimatedClientProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!containerRef.current) return undefined;
    const root = containerRef.current;
    let cancelled = false;

    (async () => {
      try {
        const mod = await import("gsap");
        if (cancelled) return;
        const gsap = mod.gsap ?? mod.default;
        const targets = root.querySelectorAll(".marketing-fade-in");
        if (targets.length === 0) return;
        targets.forEach((node) => {
          (node as HTMLElement).style.animation = "none";
        });
        gsap.fromTo(
          targets,
          { opacity: 0, y: 16 },
          {
            opacity: 1,
            y: 0,
            duration: 0.6,
            ease: "power2.out",
            stagger: 0.08,
          }
        );
      } catch {
        // gsap failed to load — CSS fade-in still runs. No-op.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div ref={containerRef} className="marketing-inner marketing-inner--wide">
      {children}
    </div>
  );
}
