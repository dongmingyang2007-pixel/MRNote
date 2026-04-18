import type { ReactNode } from "react";

interface MockWindowProps {
  title: string;
  children: ReactNode;
  className?: string;
  style?: React.CSSProperties;
  /**
   * When `true` (the default), the window chrome is marked
   * `aria-hidden` — mocks are decorative and the surrounding text
   * carries the semantic weight. Set to `false` in contexts where the
   * user interacts with the window (e.g. draggable LiveCanvasDemo);
   * the chrome then becomes a keyboard/screen-reader-reachable
   * `role="group"` with the title as its aria-label.
   */
  decorative?: boolean;
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
  decorative = true,
}: MockWindowProps) {
  const a11yProps = decorative
    ? ({ "aria-hidden": true } as const)
    : ({ role: "group", "aria-label": title } as const);

  return (
    <div
      className={`marketing-mock${className ? ` ${className}` : ""}`}
      style={style}
      {...a11yProps}
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
