import React from "react";

// ---------------------------------------------------------------------------
// Smart folder icons
// ---------------------------------------------------------------------------

export function CircleIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="9" cy="9" r="6.5" />
    </svg>
  );
}

export function StarIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M9 2l2.12 4.3 4.74.69-3.43 3.34.81 4.72L9 12.77l-4.24 2.28.81-4.72L2.14 6.99l4.74-.69L9 2z" />
    </svg>
  );
}

export function ClockIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="9" cy="9" r="6.5" />
      <path d="M9 5.5V9l2.5 2.5" />
    </svg>
  );
}

export function PencilIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M2.5 15.5l1-4L12 3a1.41 1.41 0 0 1 2 2L5.5 13.5l-4 1z" />
      <path d="M10.5 4.5l2 2" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Category icons
// ---------------------------------------------------------------------------

export function PersonIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="9" cy="5.5" r="3" />
      <path d="M3 15.5c0-3.31 2.69-6 6-6s6 2.69 6 6" />
    </svg>
  );
}

export function HeartIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M9 15.5s-5.5-3.5-5.5-7a3 3 0 0 1 5.5-1.7A3 3 0 0 1 14.5 8.5c0 3.5-5.5 7-5.5 7z" />
    </svg>
  );
}

export function TargetIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="9" cy="9" r="6.5" />
      <circle cx="9" cy="9" r="4" />
      <circle cx="9" cy="9" r="1.5" />
    </svg>
  );
}

export function BookIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M2.5 3v12c2 -1 4.5-1 6.5 0V3C7 2 4.5 2 2.5 3z" />
      <path d="M15.5 3v12c-2-1-4.5-1-6.5 0V3c2-1 4.5-1 6.5 0z" />
    </svg>
  );
}

export function BubbleIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M3 3h12a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H7l-3.5 2.5V13H3a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
    </svg>
  );
}

export function LayersIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M9 2L2 6l7 4 7-4L9 2z" />
      <path d="M2 9l7 4 7-4" />
      <path d="M2 12l7 4 7-4" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Subject icons
// ---------------------------------------------------------------------------

export function LightningIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M10 2L4 10h4.5l-.5 6 6-8h-4.5L10 2z" />
    </svg>
  );
}

export function CupIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M3 4h9v7a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V4z" />
      <path d="M12 6h1.5a2 2 0 0 1 0 4H12" />
      <path d="M4 16h7" />
    </svg>
  );
}

export function PlaneIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M15.5 2.5l-13 5.5 5 2 5.5-5-4 6.5 2 5 4.5-14z" />
      <path d="M7.5 10l-1.5 5" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Action / UI icons
// ---------------------------------------------------------------------------

export function PlusIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M9 3.5v11" />
      <path d="M3.5 9h11" />
    </svg>
  );
}

export function SearchIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="7.5" cy="7.5" r="4.5" />
      <path d="M11 11l4.5 4.5" />
    </svg>
  );
}

export function GridIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <rect x="2.5" y="2.5" width="5" height="5" rx="1" />
      <rect x="10.5" y="2.5" width="5" height="5" rx="1" />
      <rect x="2.5" y="10.5" width="5" height="5" rx="1" />
      <rect x="10.5" y="10.5" width="5" height="5" rx="1" />
    </svg>
  );
}

export function ListIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M5.5 4.5h10" />
      <path d="M5.5 9h10" />
      <path d="M5.5 13.5h10" />
      <circle cx="2.75" cy="4.5" r="0.75" fill="currentColor" stroke="none" />
      <circle cx="2.75" cy="9" r="0.75" fill="currentColor" stroke="none" />
      <circle cx="2.75" cy="13.5" r="0.75" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function GraphIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="9" cy="4" r="2" />
      <circle cx="4" cy="13" r="2" />
      <circle cx="14" cy="13" r="2" />
      <path d="M7.5 5.5L5.5 11.5" />
      <path d="M10.5 5.5l2 6" />
      <path d="M6 13h6" />
    </svg>
  );
}

export function SphereIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <circle cx="9" cy="9" r="6.5" />
      <ellipse cx="9" cy="9" rx="3" ry="6.5" />
      <path d="M2.5 9h13" />
      <path d="M3.5 5.5h11" />
      <path d="M3.5 12.5h11" />
    </svg>
  );
}

export function CloseIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M4.5 4.5l9 9" />
      <path d="M13.5 4.5l-9 9" />
    </svg>
  );
}

export function ChevronRightIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M7 4l5 5-5 5" />
    </svg>
  );
}

export function ExportIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M9 3v8.5" />
      <path d="M5.5 8L9 11.5 12.5 8" />
      <path d="M3 13.5v1a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-1" />
    </svg>
  );
}

export function TrashIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M3 5h12" />
      <path d="M7 5V3.5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1V5" />
      <path d="M4.5 5l.5 10a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1l.5-10" />
      <path d="M7.5 8v4.5" />
      <path d="M10.5 8v4.5" />
    </svg>
  );
}

export function EditIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M11 3.5l3.5 3.5L7 14.5H3.5V11L11 3.5z" />
      <path d="M9.5 5l3.5 3.5" />
    </svg>
  );
}

export function ArrowUpIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" {...props}>
      <path d="M9 14.5V3.5" />
      <path d="M4.5 8L9 3.5 13.5 8" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Lookup component
// ---------------------------------------------------------------------------

const ICON_MAP: Record<string, React.FC<React.SVGProps<SVGSVGElement>>> = {
  circle: CircleIcon,
  star: StarIcon,
  clock: ClockIcon,
  pencil: PencilIcon,
  person: PersonIcon,
  heart: HeartIcon,
  target: TargetIcon,
  book: BookIcon,
  bubble: BubbleIcon,
  layers: LayersIcon,
  lightning: LightningIcon,
  cup: CupIcon,
  plane: PlaneIcon,
  plus: PlusIcon,
  search: SearchIcon,
  grid: GridIcon,
  list: ListIcon,
  graph: GraphIcon,
  sphere: SphereIcon,
  close: CloseIcon,
  chevronRight: ChevronRightIcon,
  export: ExportIcon,
  trash: TrashIcon,
  edit: EditIcon,
  arrowUp: ArrowUpIcon,
};

interface MemoryIconProps extends React.SVGProps<SVGSVGElement> {
  name: string;
}

export function MemoryIcon({ name, ...props }: MemoryIconProps) {
  const Icon = ICON_MAP[name];
  if (!Icon) return null;
  return <Icon {...props} />;
}
