import StatCounter from "./StatCounter";

interface Props {
  count: number;
  prefix: string;
  suffix: string;
  asOfTooltip: string;
}

export default function StatHeadline({ count, prefix, suffix, asOfTooltip }: Props) {
  return (
    <div className="marketing-exclusive__stat">
      {prefix ? <span className="marketing-exclusive__stat-prefix">{prefix}</span> : null}
      <strong className="marketing-exclusive__stat-number" title={asOfTooltip}>
        <StatCounter target={count} />
        <span className="marketing-exclusive__stat-plus" aria-hidden="true">+</span>
      </strong>
      <span className="marketing-exclusive__stat-suffix">{suffix}</span>
    </div>
  );
}
