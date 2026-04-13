import { type ButtonHTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";

type GlassButtonVariant = "primary" | "secondary" | "ghost";
type GlassButtonSize = "small" | "medium";

interface GlassButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: GlassButtonVariant;
  size?: GlassButtonSize;
  children: ReactNode;
}

const variantStyles: Record<GlassButtonVariant, React.CSSProperties> = {
  primary: {
    background: "var(--console-accent-gradient)",
    color: "#ffffff",
    border: "none",
    boxShadow: "var(--console-shadow-primary)",
  },
  secondary: {
    background: "rgba(255,255,255,0.6)",
    backdropFilter: "blur(8px)",
    WebkitBackdropFilter: "blur(8px)",
    color: "var(--console-text-primary)",
    border: "1px solid rgba(0,0,0,0.08)",
  },
  ghost: {
    background: "transparent",
    color: "var(--console-accent)",
    border: "1px solid rgba(37,99,235,0.3)",
  },
};

const sizeStyles: Record<GlassButtonSize, React.CSSProperties> = {
  small: { padding: "8px 12px", fontSize: "11px", minHeight: "36px" },
  medium: { padding: "10px 20px", fontSize: "12px", minHeight: "44px" },
};

export function GlassButton({
  variant = "primary",
  size = "medium",
  children,
  className,
  style,
  ...props
}: GlassButtonProps) {
  return (
    <button
      className={clsx("glass-button", `glass-button--${variant}`, className)}
      style={{
        borderRadius: "var(--console-radius-md)",
        ...sizeStyles[size],
        fontWeight: 600,
        cursor: "pointer",
        display: "inline-flex",
        alignItems: "center",
        gap: "6px",
        transition: "filter 100ms",
        ...variantStyles[variant],
        ...style,
      }}
      {...props}
    >
      {children}
    </button>
  );
}
