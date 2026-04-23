// legacy route, kept for backward compat; remove in future release.
// Spec §6.1 — memory is a floating MemoryWindow inside the workspace, not
// a dedicated page. Requests to this URL redirect to the workspace with
// the memory window opened via query param (handled by WindowManager).
import { redirect } from "next/navigation";

export default async function LegacyNotebookMemoryPage({
  params,
}: {
  params: Promise<{ notebookId: string; locale: string }>;
}) {
  const { notebookId, locale } = await params;
  redirect(`/${locale}/app/notebooks/${notebookId}?windows=memory`);
}
