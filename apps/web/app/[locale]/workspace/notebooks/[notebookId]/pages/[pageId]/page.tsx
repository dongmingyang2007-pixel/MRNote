import { redirect } from "next/navigation";

export default async function LegacyNotebookPage({
  params,
}: {
  params: Promise<{ notebookId: string; pageId: string }>;
}) {
  const { notebookId, pageId } = await params;

  redirect(`/app/notebooks/${notebookId}?openPage=${pageId}`);
}
