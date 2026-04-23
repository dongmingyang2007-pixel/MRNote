import React from "react";
import PublicHeader from "./PublicHeader";
import PublicFooter from "./PublicFooter";

interface LegalPageProps {
  title: string;
  updated: string;
  children: React.ReactNode;
}

// Conservative email regex — matches patterns like hello@mingrun-tech.com
// inside plain text nodes of the legal tree. Any email it finds becomes a
// clickable mailto: link, preserving the rest of the text around it.
const EMAIL_RE = /([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})/gi;

function linkifyText(input: string, baseKey: string): React.ReactNode {
  if (!input.includes("@")) return input;
  const parts = input.split(EMAIL_RE);
  if (parts.length <= 1) return input;
  return parts.map((part, i) => {
    if (i % 2 === 1) {
      return (
        <a key={`${baseKey}-m-${i}`} href={`mailto:${part}`}>
          {part}
        </a>
      );
    }
    return <React.Fragment key={`${baseKey}-t-${i}`}>{part}</React.Fragment>;
  });
}

function linkifyChildren(node: React.ReactNode, keyPrefix = "root"): React.ReactNode {
  return React.Children.map(node, (child, idx) => {
    const key = `${keyPrefix}-${idx}`;
    if (typeof child === "string") {
      return linkifyText(child, key);
    }
    if (React.isValidElement(child)) {
      // Do not descend into anchors — they already own their target.
      if (child.type === "a") return child;
      const childElement = child as React.ReactElement<{ children?: React.ReactNode }>;
      const grandchildren = childElement.props.children;
      if (grandchildren === undefined) return child;
      return React.cloneElement(childElement, {
        children: linkifyChildren(grandchildren, key),
      });
    }
    return child;
  });
}

export default function LegalPage({ title, updated, children }: LegalPageProps) {
  // Wrap the whole page in `.marketing-theme` so PublicHeader/PublicFooter
  // and the legal prose all resolve the teal+orange marketing palette. This
  // is what lets the CSS below read `var(--mkt-primary)` / `var(--mkt-*)`
  // instead of depending on the legacy `--brand-v2` blue token.
  return (
    <div
      className="marketing-theme"
      style={{ minHeight: "100vh", background: "var(--mkt-bg-base, #F7FEFC)" }}
    >
      <PublicHeader />
      <main
        style={{
          maxWidth: 680,
          margin: "0 auto",
          padding: "64px 24px 96px",
        }}
      >
        <h1
          className="font-display tracking-tight text-4xl md:text-5xl"
          style={{
            fontWeight: 700,
            color: "var(--mkt-text-primary, #0F2F2C)",
            marginBottom: 12,
            lineHeight: 1.1,
          }}
        >
          {title}
        </h1>
        <p
          style={{
            fontSize: "0.875rem",
            color: "var(--mkt-text-secondary, #415C59)",
            marginBottom: 56,
          }}
        >
          {updated}
        </p>

        <div className="legal-prose">{linkifyChildren(children)}</div>
      </main>
      <PublicFooter />

      <style>{`
        .legal-prose {
          color: var(--mkt-text-secondary, #415C59);
          font-size: 15px;
          line-height: 1.75;
        }

        .legal-prose h2 {
          font-family: var(--mkt-font-display);
          font-size: 1.5rem;
          font-weight: 600;
          letter-spacing: -0.015em;
          color: var(--mkt-text-primary, #0F2F2C);
          margin-top: 64px;
          margin-bottom: 16px;
          line-height: 1.25;
        }

        .legal-prose p {
          margin-bottom: 16px;
          font-size: 15px;
        }

        .legal-prose ul {
          margin: 0 0 16px;
          padding-left: 24px;
          list-style: disc;
        }

        .legal-prose li {
          margin-bottom: 10px;
          font-size: 15px;
          line-height: 1.7;
        }

        .legal-prose strong {
          color: var(--mkt-text-primary, #0F2F2C);
          font-weight: 600;
        }

        .legal-prose a {
          color: var(--mkt-primary, #0D9488);
          text-decoration: none;
          border-bottom: 1px solid rgba(13, 148, 136, 0.35);
          transition:
            color var(--mkt-dur, 220ms) var(--mkt-ease, cubic-bezier(0.32, 0.72, 0, 1)),
            border-color var(--mkt-dur, 220ms) var(--mkt-ease, cubic-bezier(0.32, 0.72, 0, 1));
        }

        .legal-prose a:hover {
          color: var(--mkt-primary-600, #0B8278);
          border-bottom-color: var(--mkt-primary-600, #0B8278);
        }

        .legal-prose .legal-note {
          background: var(--mkt-bg-tint, #F0FDFA);
          border-left: 3px solid var(--mkt-primary, #0D9488);
          padding: 14px 18px;
          border-radius: 0 8px 8px 0;
          margin: 20px 0;
          font-size: 14px;
          line-height: 1.65;
        }
      `}</style>
    </div>
  );
}
