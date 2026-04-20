interface Props {
  quote: string;
  name: string;
  title: string;
  avatarInitial: string;
}

export default function TestimonialStrip({ quote, name, title, avatarInitial }: Props) {
  return (
    <figure className="marketing-exclusive__testimonial">
      <div className="marketing-exclusive__testimonial-avatar" aria-hidden="true">
        {avatarInitial}
      </div>
      <div>
        <blockquote className="marketing-exclusive__testimonial-quote">
          &ldquo;{quote}&rdquo;
        </blockquote>
        <figcaption className="marketing-exclusive__testimonial-attr">
          {name} · {title}
        </figcaption>
      </div>
    </figure>
  );
}
