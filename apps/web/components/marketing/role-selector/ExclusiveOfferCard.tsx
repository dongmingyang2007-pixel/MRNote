import { Link } from "@/i18n/navigation";
import { Gift } from "lucide-react";

interface Props {
  label: string;
  title: string;
  description: string;
  cta: string;
  href: string;
  badge: string;
  onClick?: () => void;
}

export default function ExclusiveOfferCard({ label, title, description, cta, href, badge, onClick }: Props) {
  return (
    <div className="marketing-exclusive__card marketing-exclusive__card--offer">
      <span className="marketing-exclusive__offer-badge">
        <Gift size={11} strokeWidth={2.25} aria-hidden="true" />
        {badge}
      </span>
      <span className="marketing-exclusive__card-label marketing-exclusive__card-label--offer">
        {label}
      </span>
      <h4 className="marketing-exclusive__card-title">{title}</h4>
      <p className="marketing-exclusive__card-body">{description}</p>
      <Link href={href} className="marketing-exclusive__offer-cta" onClick={onClick}>
        {cta}
      </Link>
    </div>
  );
}
