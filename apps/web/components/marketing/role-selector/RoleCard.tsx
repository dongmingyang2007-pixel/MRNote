interface Props {
  label: string;
  title: string;
  description: string;
  cta?: string;
  mediaSlot?: React.ReactNode;
}

export default function RoleCard({ label, title, description, cta, mediaSlot }: Props) {
  return (
    <div className="marketing-exclusive__card">
      <span className="marketing-exclusive__card-label">{label}</span>
      <h4 className="marketing-exclusive__card-title">{title}</h4>
      <p className="marketing-exclusive__card-body">{description}</p>
      {mediaSlot ? <div className="marketing-exclusive__card-media">{mediaSlot}</div> : null}
      {cta ? <span className="marketing-exclusive__card-cta">{cta}</span> : null}
    </div>
  );
}
