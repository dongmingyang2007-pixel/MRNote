import {
  Book,
  Check,
  FileText,
  Network,
  NotebookPen,
  Sparkles,
  SquareStack,
  type LucideIcon,
} from "lucide-react";

/** Lucide icon lookup for DigestItemMock.icon keys. Kept as a pure map so
 *  the server render and client hydration agree. */
export const DIGEST_ITEM_ICONS: Record<string, LucideIcon> = {
  note: NotebookPen,
  sparkles: Sparkles,
  cards: SquareStack,
  book: Book,
  graph: Network,
  file: FileText,
  check: Check,
};

export function DigestItemIcon({ name, size = 13 }: { name: string; size?: number }) {
  const Icon = DIGEST_ITEM_ICONS[name] ?? Sparkles;
  return <Icon size={size} aria-hidden="true" />;
}
