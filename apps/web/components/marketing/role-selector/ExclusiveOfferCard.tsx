import { Link } from "@/i18n/navigation";

interface Props {
  title: string;
  description: string;
  cta: string;
  href: string;
  badge: string;
  onClick?: () => void;
}

export default function ExclusiveOfferCard({ title, description, cta, href, badge, onClick }: Props) {
  return (
    <div className="marketing-exclusive__card marketing-exclusive__card--offer">
      <span className="marketing-exclusive__offer-badge">{badge}</span>
      <span className="marketing-exclusive__card-label marketing-exclusive__card-label--offer">
        专属优惠
      </span>
      <h4 className="marketing-exclusive__card-title">{title}</h4>
      <p className="marketing-exclusive__card-body">{description}</p>
      <Link href={href} className="marketing-exclusive__offer-cta" onClick={onClick}>
        {cta}
      </Link>
    </div>
  );
}
