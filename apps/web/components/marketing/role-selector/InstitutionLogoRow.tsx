interface Props {
  heading: string;
  names: string[];
}

export default function InstitutionLogoRow({ heading, names }: Props) {
  return (
    <div className="marketing-exclusive__logos">
      <div className="marketing-exclusive__logos-heading">{heading}</div>
      <ul className="marketing-exclusive__logos-list">
        {names.map((name) => (
          <li key={name} className="marketing-exclusive__logos-item">{name}</li>
        ))}
      </ul>
    </div>
  );
}
