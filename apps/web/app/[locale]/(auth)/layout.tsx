import AuthBrandHeader from "@/components/marketing/AuthBrandHeader";
import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";

/**
 * Auth layout — single-column centered, the way Linear / Notion / Vercel /
 * Stripe do it. Users reach /login because they already know the product;
 * a marketing panel here is noise. Logo sits quietly at top-left, form
 * carries all the weight, terms + privacy footer sits muted at bottom.
 */
export default async function AuthLayout({ children }: { children: React.ReactNode }) {
  const tAuth = await getTranslations("auth");

  return (
    <div className="flex min-h-screen flex-col bg-[var(--bg-base)] text-[var(--text-primary)]">
      <AuthBrandHeader />

      {/* Form — single column, centered, max-w-sm. */}
      <main className="flex flex-1 items-center justify-center px-6 py-16">
        <div className="w-full max-w-[400px]">{children}</div>
      </main>

      {/* Muted legal footer. */}
      <footer className="px-6 pb-8 text-center text-xs text-[var(--text-secondary)] md:px-10">
        <div className="inline-flex items-center gap-4">
          <Link href="/terms" className="hover:text-[var(--text-primary)]">
            {tAuth("footer.terms")}
          </Link>
          <span className="text-[var(--border)]">·</span>
          <Link href="/privacy" className="hover:text-[var(--text-primary)]">
            {tAuth("footer.privacy")}
          </Link>
        </div>
      </footer>
    </div>
  );
}
