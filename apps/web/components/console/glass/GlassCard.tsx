import { type ReactNode } from "react";
import clsx from "clsx";

interface GlassCardProps {
  children: ReactNode;
  className?: string;
  hover?: boolean;
  style?: React.CSSProperties;
}

export function GlassCard({ children, className, hover = false, style }: GlassCardProps) {
  return (
    <div
      className={clsx("glass-card", hover && "glass-card--hover", className)}
      style={{
        background: "var(--console-surface)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        border: "1px solid var(--console-border)",
        borderRadius: "var(--console-radius-lg)",
        padding: "20px",
        boxShadow: "var(--console-shadow-card)",
        ...style,
      }}
    >
      {children}
    </div>
  );
}
