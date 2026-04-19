import MockWindow from "./MockWindow";

/**
 * Feature 1 — "持久记忆". Shows three memory rows extracted from a
 * client conversation. The last row ends with a blinking caret to
 * suggest it's being written in real-time, reinforcing the
 * "auto-extracted" promise of the feature.
 */
interface MemoryMockProps {
  style?: React.CSSProperties;
  decorative?: boolean;
}

export default function MemoryMock({ style, decorative }: MemoryMockProps) {
  return (
    <MockWindow title="Memory · Sarah Chen" style={style} decorative={decorative}>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">Quote</span>
        <span className="marketing-mock__row-value">$18K, delivery in 6 weeks</span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">Prefers</span>
        <span className="marketing-mock__row-value">Async updates, no weekly calls</span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">Next</span>
        <span className="marketing-mock__row-value">
          Send revised SOW by Fri
          <span className="marketing-mock__caret" />
        </span>
      </div>
    </MockWindow>
  );
}
