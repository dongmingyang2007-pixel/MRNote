import { PageTransition } from "@/components/console/PageTransition";
import { redirect } from "next/navigation";
import { DISCOVER_ENABLED } from "@/lib/feature-flags";

export const dynamic = "force-dynamic";

export default async function PackDetailPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale } = await params;

  if (!DISCOVER_ENABLED) {
    redirect(locale === "en" ? "/en/app" : "/app");
  }

  return (
    <PageTransition>
      <div style={{ padding: "24px 32px", maxWidth: 800 }}>
        <div
          style={{
            position: "relative",
            border:
              "1px solid color-mix(in srgb, var(--accent) 10%, var(--border))",
            borderRadius: 26,
            background:
              "linear-gradient(180deg, color-mix(in srgb, var(--bg-card) 94%, white), var(--bg-card))",
            boxShadow: "0 18px 40px rgba(42, 32, 24, 0.05)",
            padding: 24,
          }}
        >
          <h1
            style={{
              fontSize: 20,
              fontWeight: 700,
              color: "var(--text-primary)",
              marginBottom: 8,
            }}
          >
            记忆包详情
          </h1>
          <p
            style={{
              fontSize: 13,
              color: "var(--text-secondary)",
              lineHeight: 1.6,
            }}
          >
            记忆包详情页将在后续迭代中完善。
          </p>
        </div>
      </div>
    </PageTransition>
  );
}
