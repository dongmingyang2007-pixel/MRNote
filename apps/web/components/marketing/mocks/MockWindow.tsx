import type { ReactNode } from "react";

interface MockWindowProps {
  title: string;
  children: ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Marketing-only window chrome. Mirrors the real WindowManager frame
 * at a smaller scale (traffic lights + title + bordered body). All
 * three feature mocks render inside this shell so the hero, the
 * features, and the live-canvas demo share one visual language.
 *
 * Server component — no state, no refs.
 */
export default function MockWindow({
  title,
  children,
  className,
  style,
}: MockWindowProps) {
  return (
    <div
      className={`marketing-mock${className ? ` ${className}` : ""}`}
      style={style}
      aria-hidden="true"
    >
      <div className="marketing-mock__titlebar">
        <div className="marketing-mock__lights">
          <span className="marketing-mock__light marketing-mock__light--red" />
          <span className="marketing-mock__light marketing-mock__light--yellow" />
          <span className="marketing-mock__light marketing-mock__light--green" />
        </div>
        <span className="marketing-mock__title">{title}</span>
      </div>
      <div className="marketing-mock__body">{children}</div>
    </div>
  );
}
