import MockWindow from "./MockWindow";

/**
 * Feature 2 — "跟进提醒". Two due-today items with pulsing brand-blue
 * dots + one 45-day dormant client warning in amber. The pulse is the
 * "nudge" motion; no timer or wall-clock logic — it's purely visual.
 */
interface FollowupMockProps {
  style?: React.CSSProperties;
  decorative?: boolean;
}

export default function FollowupMock({ style, decorative }: FollowupMockProps) {
  return (
    <MockWindow title="Follow-ups · Due today" style={style} decorative={decorative}>
      <div className="marketing-mock__row">
        <span className="marketing-mock__dot marketing-mock__dot--pulse" />
        <span className="marketing-mock__row-value">
          Send proposal to <strong>Lisa Patel</strong> · promised Mon
        </span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__dot marketing-mock__dot--pulse" />
        <span className="marketing-mock__row-value">
          Revise Q3 SOW for <strong>Sarah Chen</strong>
        </span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__dot marketing-mock__dot--amber" />
        <span className="marketing-mock__row-value">
          <strong>David Kim</strong> — 45 days since last reply
        </span>
      </div>
    </MockWindow>
  );
}
