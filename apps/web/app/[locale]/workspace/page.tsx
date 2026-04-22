import { redirect } from "next/navigation";

export default function WorkspaceRootPage() {
  redirect("/app/notebooks");
}
