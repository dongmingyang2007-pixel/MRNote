interface Props {
  label: string;
  title: string;
  description: string;
  cta?: string;
  mediaSlot?: React.ReactNode;
  variant?: "default" | "feature";
}

export default function RoleCard({ label, title, description, cta, mediaSlot, variant = "default" }: Props) {
  const className =
    variant === "feature"
      ? "marketing-exclusive__card marketing-exclusive__card--feature"
      : "marketing-exclusive__card";
  return (
    <div className={className}>
      <span className="marketing-exclusive__card-label">{label}</span>
      <h4 className="marketing-exclusive__card-title">{title}</h4>
      <p className="marketing-exclusive__card-body">{description}</p>
      {mediaSlot ? <div className="marketing-exclusive__card-media">{mediaSlot}</div> : null}
      {cta ? <span className="marketing-exclusive__card-cta">{cta}</span> : null}
    </div>
  );
}
