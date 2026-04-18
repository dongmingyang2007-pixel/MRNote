import MockWindow from "./MockWindow";

/**
 * Feature 3 — "每周反思". Monday digest preview. Three compressed
 * bullets giving the feeling of a "weekly at a glance". No motion —
 * this one is intentionally calm to contrast with the pulsing
 * FollowupMock.
 */
export default function DigestMock({ style }: { style?: React.CSSProperties }) {
  return (
    <MockWindow title="Monday Digest · Wk 16" style={style}>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">Done</span>
        <span className="marketing-mock__row-value">
          14 conversations · 6 clients touched
        </span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">Overdue</span>
        <span className="marketing-mock__row-value">
          2 promises past due — Lisa, Marco
        </span>
      </div>
      <div className="marketing-mock__row">
        <span className="marketing-mock__row-label">Drift</span>
        <span className="marketing-mock__row-value">
          Sarah's scope +32% vs. original SOW
        </span>
      </div>
    </MockWindow>
  );
}
