// legacy route, kept for backward compat; remove in future release.
// Spec §6.1 — pages no longer have their own route. Incoming links here
// are redirected back to the notebook workspace with ?openPage=, which
// WindowManager consumes on mount to open the note window.
import { redirect } from "next/navigation";

export default async function LegacyNotebookPage({
  params,
}: {
  params: Promise<{ notebookId: string; pageId: string }>;
}) {
  const { notebookId, pageId } = await params;

  redirect(`/app/notebooks/${notebookId}?openPage=${pageId}`);
}
