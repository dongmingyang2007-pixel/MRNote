import { redirect } from "next/navigation";
import DiscoverPageClient from "./_components/DiscoverPageClient";
import {
  DISCOVER_ENABLED,
  resolveDiscoverRedirectTarget,
} from "@/lib/feature-flags";

export const dynamic = "force-dynamic";

export default async function DiscoverPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ from?: string | string[] }>;
}) {
  const [{ locale }, rawSearchParams] = await Promise.all([
    params,
    searchParams,
  ]);
  const from =
    typeof rawSearchParams.from === "string" ? rawSearchParams.from : null;

  if (!DISCOVER_ENABLED) {
    redirect(resolveDiscoverRedirectTarget(locale, from));
  }

  return <DiscoverPageClient />;
}
