import { type ReactNode } from "react";
import clsx from "clsx";

interface GlassPanelProps {
  children: ReactNode;
  className?: string;
}

export function GlassPanel({ children, className }: GlassPanelProps) {
  return (
    <div
      className={clsx("glass-panel", className)}
      style={{
        background: "var(--console-panel)",
        backdropFilter: "blur(16px)",
        WebkitBackdropFilter: "blur(16px)",
        border: "1px solid var(--console-border-subtle)",
        borderRadius: "var(--console-radius-lg)",
      }}
    >
      {children}
    </div>
  );
}
