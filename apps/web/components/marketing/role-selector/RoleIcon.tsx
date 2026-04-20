import { BookOpen, GraduationCap, Palette, Rocket, Scale, Stethoscope, type LucideIcon } from "lucide-react";
import type { RoleIconKey } from "@/lib/marketing/role-content";

const MAP: Record<RoleIconKey, LucideIcon> = {
  "graduation-cap": GraduationCap,
  scale: Scale,
  stethoscope: Stethoscope,
  "book-open": BookOpen,
  rocket: Rocket,
  palette: Palette,
};

interface Props {
  iconKey: RoleIconKey;
  size?: number;
  strokeWidth?: number;
  className?: string;
}

export default function RoleIcon({ iconKey, size = 20, strokeWidth = 1.75, className }: Props) {
  const Icon = MAP[iconKey];
  return <Icon size={size} strokeWidth={strokeWidth} className={className} aria-hidden="true" />;
}
