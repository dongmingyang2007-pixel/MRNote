import MockWindow from "./MockWindow";

/**
 * Feature 3 — "每周反思". Monday digest preview. Three compressed
 * bullets giving the feeling of a "weekly at a glance". No motion —
 * this one is intentionally calm to contrast with the pulsing
 * FollowupMock.
 */
interface DigestMockProps {
  style?: React.CSSProperties;
  decorative?: boolean;
}

export default function DigestMock({ style, decorative }: DigestMockProps) {
  return (
    <MockWindow title="Monday Digest · Wk 16" style={style} decorative={decorative}>
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
          Sarah&apos;s scope +32% vs. original SOW
        </span>
      </div>
    </MockWindow>
  );
}
