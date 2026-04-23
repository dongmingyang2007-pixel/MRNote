// legacy route, kept for backward compat; remove in future release.
// Spec §6.1 — notebooks no longer have dedicated page routes; chat is a
// floating AIPanel window inside the workspace. Any incoming links to
// this URL get redirected to the workspace with the AI panel opened.
import { redirect } from "next/navigation";

export default async function LegacyNotebookChatPage({
  params,
}: {
  params: Promise<{ notebookId: string; locale: string }>;
}) {
  const { notebookId, locale } = await params;
  redirect(`/${locale}/app/notebooks/${notebookId}?windows=ai_panel`);
}
