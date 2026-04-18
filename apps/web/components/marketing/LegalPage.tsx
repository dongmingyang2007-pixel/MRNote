import PublicHeader from "./PublicHeader";
import PublicFooter from "./PublicFooter";

interface LegalPageProps {
  title: string;
  updated: string;
  children: React.ReactNode;
}

export default function LegalPage({ title, updated, children }: LegalPageProps) {
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-base)" }}>
      <PublicHeader />
      <main
        style={{
          maxWidth: 720,
          margin: "0 auto",
          padding: "64px 24px 96px",
        }}
      >
        <h1
          style={{
            fontSize: "2rem",
            fontWeight: 700,
            color: "var(--text-primary, #f1f5f9)",
            marginBottom: 8,
            lineHeight: 1.2,
          }}
        >
          {title}
        </h1>
        <p
          style={{
            fontSize: "0.875rem",
            color: "var(--text-tertiary, #64748b)",
            marginBottom: 48,
          }}
        >
          {updated}
        </p>

        <div className="legal-prose">{children}</div>
      </main>
      <PublicFooter />

      <style>{`
        .legal-prose {
          color: var(--text-secondary, #cbd5e1);
          font-size: 1rem;
          line-height: 1.7;
        }

        .legal-prose h2 {
          font-size: 1.375rem;
          font-weight: 700;
          color: var(--text-primary, #f1f5f9);
          margin-top: 48px;
          margin-bottom: 16px;
          line-height: 1.3;
        }

        .legal-prose p {
          margin-bottom: 16px;
        }

        .legal-prose ul {
          margin-bottom: 16px;
          padding-left: 24px;
          list-style: disc;
        }

        .legal-prose li {
          margin-bottom: 8px;
        }

        .legal-prose strong {
          color: var(--text-primary, #f1f5f9);
          font-weight: 600;
        }

        .legal-prose a {
          color: var(--accent, #3b82f6);
          text-decoration: underline;
        }

        .legal-prose a:hover {
          color: var(--accent-hover, #60a5fa);
        }

        .legal-prose .legal-note {
          background: var(--bg-card, #1e293b);
          border-left: 3px solid var(--accent, #3b82f6);
          padding: 12px 16px;
          border-radius: 0 6px 6px 0;
          margin-bottom: 16px;
          font-size: 0.9rem;
        }
      `}</style>
    </div>
  );
}
