import { type InputHTMLAttributes, forwardRef } from "react";
import clsx from "clsx";

interface GlassInputProps extends InputHTMLAttributes<HTMLInputElement> {
  icon?: React.ReactNode;
}

export const GlassInput = forwardRef<HTMLInputElement, GlassInputProps>(
  ({ className, icon, style, ...props }, ref) => (
    <div
      className={clsx("glass-input-wrapper", className)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "8px",
        background: "rgba(255,255,255,0.8)",
        border: "1px solid var(--console-border)",
        borderRadius: "var(--console-radius-md)",
        padding: "10px 14px",
        ...style,
      }}
    >
      {icon}
      <input
        ref={ref}
        style={{
          flex: 1,
          background: "transparent",
          border: "none",
          outline: "none",
          fontSize: "13px",
          color: "var(--console-text-primary)",
          minHeight: "24px",
        }}
        {...props}
      />
    </div>
  )
);
GlassInput.displayName = "GlassInput";
