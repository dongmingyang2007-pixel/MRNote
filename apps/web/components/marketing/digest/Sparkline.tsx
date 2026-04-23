/** 7-point SVG sparkline for weekly reflection. Normalized 0..1 input.
 *  stroke-dasharray animation is defined in marketing.css and gets a
 *  unique `--dash-len` hint so the draw-in feels like handwriting. */
export default function Sparkline({
  values,
  label,
}: {
  values: number[];
  label: string;
}) {
  const width = 600;
  const height = 60;
  const step = width / (values.length - 1 || 1);
  const pts = values.map((v, i) => {
    const x = Math.round(i * step);
    // Invert y (SVG origin top-left), leave 6px top/bottom padding
    const y = Math.round(6 + (1 - Math.max(0, Math.min(1, v))) * (height - 12));
    return [x, y] as const;
  });

  const pathD = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x} ${y}`).join(" ");
  const fillD = `${pathD} L ${pts[pts.length - 1][0]} ${height} L ${pts[0][0]} ${height} Z`;

  return (
    <div className="marketing-weekly__sparkline" role="img" aria-label={label}>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id="mrai-spark-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--color-secondary, #14B8A6)" stopOpacity="0.28" />
            <stop offset="100%" stopColor="var(--color-secondary, #14B8A6)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={fillD} fill="url(#mrai-spark-fill)" />
        <path
          className="marketing-weekly__sparkline-line"
          d={pathD}
          stroke="var(--color-secondary, #14B8A6)"
          strokeWidth="1.6"
          fill="none"
        />
        {pts.map(([x, y], i) => (
          <circle
            key={i}
            cx={x}
            cy={y}
            r="2.5"
            fill="var(--color-secondary, #14B8A6)"
            className="marketing-weekly__sparkline-dot"
            style={{ animationDelay: `${i * 80}ms` }}
          />
        ))}
      </svg>
    </div>
  );
}
