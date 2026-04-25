import { cookies } from "next/headers";

const AUTH_COOKIE_NAMES = [
  "auth_state",
  "mrnote_workspace_id",
  "mingrun_workspace_id",
  "qihang_workspace_id",
] as const;

export async function isLoggedInFromCookies(): Promise<boolean> {
  const store = await cookies();
  return AUTH_COOKIE_NAMES.some((name) => Boolean(store.get(name)));
}
