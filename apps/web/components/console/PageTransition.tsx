import type { ReactNode } from "react";

// Plain server-renderable wrapper: the entrance animation is pure CSS so
// SSR and the first client render produce identical HTML (no hydration
// mismatch). Previously this used framer-motion's `<motion.div initial=…>`
// which injected a different inline style on the client and tripped React
// hydration on every notebook-library navigation.
export function PageTransition({ children }: { children: ReactNode }) {
  return <div className="page-transition">{children}</div>;
}
